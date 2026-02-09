# Uderia Platform REST API - n8n Reference

**Version:** 1.0
**Last Updated:** February 9, 2026
**Purpose:** Complete technical reference for integrating Uderia with n8n workflows

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication](#2-authentication)
3. [Session Management](#3-session-management)
4. [Query Execution](#4-query-execution)
5. [Task Management](#5-task-management)
6. [Response Schemas](#6-response-schemas)
7. [Error Handling](#7-error-handling)
8. [n8n-Specific Tips](#8-n8n-specific-tips)
9. [Code Snippets Library](#9-code-snippets-library)
10. [Troubleshooting Guide](#10-troubleshooting-guide)

---

## 1. Overview

### 1.1. Base URL Configuration

All API endpoints are relative to your Uderia instance:

```
http://your-uderia-host:5050/api
```

**Local Development:**
```
http://localhost:5050/api
http://127.0.0.1:5050/api
```

**n8n HTTP Request Node Configuration:**
```
Base URL: http://localhost:5050
```

### 1.2. API Architecture

Uderia uses an **asynchronous task-based architecture**:

1. **Submit** a query → Get `task_id`
2. **Poll** task status → Check `status` field
3. **Retrieve** result when `status === "complete"`

This pattern is ideal for long-running AI agent operations without holding connections open.

### 1.3. Authentication Methods

| Method | Format | Lifetime | Best For |
|--------|--------|----------|----------|
| **Access Token** | `tda_xxxxx...` | 90 days (configurable) | n8n automation |
| **JWT Token** | `eyJhbGci...` | 24 hours | Interactive testing |

**Recommendation for n8n:** Use **Access Tokens** (long-lived, no refresh needed).

### 1.4. Prerequisites

Before using Uderia REST API, ensure:

1. ✅ User account created
2. ✅ Access token generated
3. ✅ **Default profile configured** (LLM + MCP Server)
4. ✅ Profile set as default in UI

Without a default profile, session creation will return `400 Bad Request`.

---

## 2. Authentication

### 2.1. Login to Get JWT

Use this method for initial token generation or interactive testing.

**Endpoint:** `POST /auth/login`
**Authentication:** None (uses credentials)

**Request:**
```http
POST http://localhost:5050/auth/login
Content-Type: application/json

{
  "username": "your_username",
  "password": "your_password"
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX3V1aWQiOiJhZG1pbl81NTBlODQwMCIsImV4cCI6MTczODY0MjgwMH0.abc123...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "your_username",
    "email": "user@example.com",
    "user_uuid": "your_username_550e8400"
  }
}
```

**Error Responses:**
- `401 Unauthorized` - Invalid username or password
- `429 Too Many Requests` - Rate limit exceeded (5 attempts/minute)

**n8n Configuration:**

**HTTP Request Node:**
```
Method: POST
URL: http://localhost:5050/auth/login
Authentication: None
Body Content Type: JSON
Body:
{
  "username": "{{$json.username}}",
  "password": "{{$json.password}}"
}
```

**Extract Token (Code Node):**
```javascript
return {
  json: {
    jwt_token: $json.token,
    user_uuid: $json.user.user_uuid,
    expires_at: Date.now() + (24 * 60 * 60 * 1000) // 24 hours
  }
};
```

---

### 2.2. Create Access Token (Recommended for n8n)

Generate a long-lived API token for automation.

**Endpoint:** `POST /api/v1/auth/tokens`
**Authentication:** Required (JWT token from login)

**Request:**
```http
POST http://localhost:5050/api/v1/auth/tokens
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Content-Type: application/json

{
  "name": "n8n Integration",
  "expires_in_days": 90
}
```

**Request Parameters:**
- `name` (string, required): Descriptive name for the token (e.g., "Production n8n")
- `expires_in_days` (integer, required): Token lifetime in days
  - Options: `30`, `60`, `90`, `180`, `365`, or `0` (never expires)

**Response (200 OK):**
```json
{
  "status": "success",
  "token": "tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p",
  "token_id": "abc123-def456-ghi789",
  "name": "n8n Integration",
  "created_at": "2026-02-09T10:00:00Z",
  "expires_at": "2026-05-10T10:00:00Z"
}
```

⚠️ **CRITICAL:** Copy the `token` value immediately! It cannot be retrieved later.

**Error Responses:**
- `401 Unauthorized` - JWT token invalid or expired
- `400 Bad Request` - Invalid parameters (e.g., expires_in_days not in allowed list)

**n8n Configuration:**

**HTTP Request Node:**
```
Method: POST
URL: http://localhost:5050/api/v1/auth/tokens
Authentication: Header Auth
  Header Name: Authorization
  Header Value: Bearer {{$('Login').item.json.jwt_token}}
Body Content Type: JSON
Body:
{
  "name": "n8n Integration",
  "expires_in_days": 90
}
```

**Store Token (Set Node):**
```
Values to Set:
  access_token: {{$json.token}}
  token_expires_at: {{$json.expires_at}}
  token_name: {{$json.name}}
```

---

### 2.3. Using Access Tokens in n8n

**Method 1: n8n Credentials (Recommended)**

1. Navigate to: **n8n Settings → Credentials → New**
2. Select: **Header Auth**
3. Configure:
   ```
   Credential Name: Uderia API Token
   Header Name: Authorization
   Header Value: Bearer tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
   ```
4. Save and use in all HTTP Request nodes

**Method 2: Workflow Variable**

Store token in workflow static data:

```javascript
// Store (in Code node after token creation)
const staticData = this.getWorkflowStaticData('global');
staticData.uderia_token = 'tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p';
staticData.token_expires_at = '2026-05-10T10:00:00Z';

// Retrieve (in subsequent Code nodes)
const token = this.getWorkflowStaticData('global').uderia_token;
```

---

## 3. Session Management

Sessions maintain conversation context across multiple queries. Each session is isolated per user.

### 3.1. Create Session

**Endpoint:** `POST /api/v1/sessions`
**Authentication:** Required (Bearer token)

**Request:**
```http
POST http://localhost:5050/api/v1/sessions
Authorization: Bearer tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
```

**Request Body:** None (uses user's default profile)

**Response (200 OK):**
```json
{
  "session_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef"
}
```

**Error Responses:**

**401 Unauthorized:**
```json
{
  "error": "Authentication required"
}
```

**400 Bad Request (No Default Profile):**
```json
{
  "error": "No default profile configured for this user. Please configure a profile (LLM + MCP Server combination) in the Configuration panel first."
}
```

**503 Service Unavailable (Incomplete Profile):**
```json
{
  "error": "Profile is incomplete. LLM Provider is required."
}
```

**n8n Configuration:**

**HTTP Request Node:**
```
Node Name: Create Session
Method: POST
URL: http://localhost:5050/api/v1/sessions
Authentication: Use Credential → Uderia API Token
Options:
  Response Format: JSON
  Full Response: OFF
```

**Store Session ID (Set Node):**
```
Mode: Manual Mapping
Values to Set:
  session_id: {{$json.session_id}}
  created_at: {{$now}}
```

**Error Handling (If Node after HTTP Request):**
```
Condition: {{$json.error}} exists
True → Send notification: "Please configure default profile in Uderia UI"
False → Continue to query submission
```

---

### 3.2. Profile Override (Optional)

You can create a session with a specific profile instead of the default:

**Request:**
```http
POST http://localhost:5050/api/v1/sessions
Authorization: Bearer tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
Content-Type: application/json

{
  "profile_id": "profile-1764006444002-z0hdduce9"
}
```

**n8n Configuration:**
```
Body Content Type: JSON
Body:
{
  "profile_id": "{{$json.override_profile_id}}"
}
```

---

### 3.3. Session Reuse for Multi-Turn Conversations

Sessions maintain conversation history. Reuse the same `session_id` for context-aware queries:

**n8n Pattern:**
```javascript
// First query
const sessionId = $('Create Session').item.json.session_id;

// Store in workflow static data
const staticData = this.getWorkflowStaticData('global');
staticData.current_session_id = sessionId;

// Subsequent queries
const existingSession = staticData.current_session_id;
// Use existingSession instead of creating new session
```

**Benefits:**
- Agent remembers previous queries
- Follow-up questions work correctly (e.g., "Show tables in the first database")
- Reduced API calls (no need to create new session each time)

**Session Expiry:**
- Sessions expire after **24 hours of inactivity**
- Create new session if 404 error on query submission

---

### 3.4. List Sessions (Optional)

Get all sessions for the authenticated user.

**Endpoint:** `GET /api/v1/sessions`
**Authentication:** Required

**Query Parameters:**
- `sort` (optional): `recent`, `oldest`, `tokens`, `turns` (default: `recent`)
- `limit` (optional): Maximum results (default: 100)
- `offset` (optional): Pagination offset (default: 0)

**Response (200 OK):**
```json
{
  "sessions": [
    {
      "id": "session-uuid",
      "name": "Data Analysis Session",
      "created_at": "2026-02-09T10:00:00Z",
      "last_updated": "2026-02-09T10:15:00Z",
      "provider": "Google",
      "model": "gemini-2.0-flash-exp",
      "input_tokens": 5000,
      "output_tokens": 3000,
      "turn_count": 3,
      "status": "success"
    }
  ],
  "total": 42
}
```

---

## 4. Query Execution

### 4.1. Submit Query

Submit a natural language query to a session. This creates a background task.

**Endpoint:** `POST /api/v1/sessions/{session_id}/query`
**Authentication:** Required

**URL Parameters:**
- `session_id` (string, required): Session UUID from "Create Session"

**Request:**
```http
POST http://localhost:5050/api/v1/sessions/a1b2c3d4-e5f6-7890-1234-567890abcdef/query
Authorization: Bearer tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
Content-Type: application/json

{
  "prompt": "Show me all databases available on the system"
}
```

**Request Body:**
```json
{
  "prompt": "Your natural language query here",
  "profile_id": "profile-optional-override"
}
```

**Parameters:**
- `prompt` (string, required): Natural language query (1-5000 characters)
- `profile_id` (string, optional): Override profile for this query only

**Response (200 OK):**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status_url": "/api/v1/tasks/task-9876-5432-1098-7654"
}
```

**Error Responses:**
- `404 Not Found` - Session not found or expired
- `400 Bad Request` - Missing or invalid prompt
- `401 Unauthorized` - Authentication required

**n8n Configuration:**

**HTTP Request Node:**
```
Node Name: Submit Query
Method: POST
URL: http://localhost:5050/api/v1/sessions/{{$('Store Session').item.json.session_id}}/query
Authentication: Uderia API Token
Body Content Type: JSON
Body:
{
  "prompt": "{{$json.user_question}}"
}
```

**Store Task ID (Set Node):**
```
Values to Set:
  task_id: {{$json.task_id}}
  status: "pending"
  poll_count: 0
  max_polls: 30
```

---

### 4.2. Profile Override Examples

**Use Case 1: Multi-LLM Routing**
```json
{
  "prompt": "Explain quantum computing in detail",
  "profile_id": "profile-gpt4-advanced"
}
```

**Use Case 2: MCP Server Switching**
```json
{
  "prompt": "Query MongoDB documents",
  "profile_id": "profile-mongodb-connector"
}
```

**n8n Dynamic Profile Selection:**
```javascript
// Select profile based on query complexity
const query = $json.prompt.toLowerCase();
let profileId = null; // Use default

if (query.includes("explain") || query.includes("analyze")) {
  profileId = "profile-gpt4-thinker"; // Expensive, accurate
} else if (query.includes("list") || query.includes("show")) {
  profileId = "profile-gemini-fast"; // Cheap, fast
}

return {
  json: {
    prompt: $json.prompt,
    profile_id: profileId
  }
};
```

---

## 5. Task Management

### 5.1. Poll Task Status

Poll this endpoint repeatedly until `status === "complete"` or `status === "error"`.

**Endpoint:** `GET /api/v1/tasks/{task_id}`
**Authentication:** Required

**URL Parameters:**
- `task_id` (string, required): Task ID from "Submit Query"

**Request:**
```http
GET http://localhost:5050/api/v1/tasks/task-9876-5432-1098-7654
Authorization: Bearer tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
```

**Response Structure:**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status": "string",
  "last_updated": "2026-02-09T10:15:00Z",
  "events": [ ... ],
  "intermediate_data": [ ... ],
  "result": { ... } or null
}
```

**Status Values:**

| Status | Description | Action |
|--------|-------------|--------|
| `pending` | Task queued, not started | Keep polling |
| `processing` | Execution in progress | Keep polling |
| `complete` | Task finished successfully | Extract result |
| `error` | Execution failed | Handle error |
| `cancelled` | User cancelled task | Handle cancellation |

---

### 5.2. Status: pending

Task has been submitted but not yet started.

**Response:**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status": "pending",
  "last_updated": "2026-02-09T10:15:00Z",
  "events": [],
  "intermediate_data": [],
  "result": null
}
```

**Action:** Continue polling.

---

### 5.3. Status: processing

Task is actively executing.

**Response:**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status": "processing",
  "last_updated": "2026-02-09T10:15:05Z",
  "events": [
    {
      "timestamp": "2026-02-09T10:15:01Z",
      "event_type": "plan_generated",
      "event_data": {
        "phase_count": 2
      }
    },
    {
      "timestamp": "2026-02-09T10:15:03Z",
      "event_type": "phase_start",
      "event_data": {
        "phase": 1,
        "goal": "Execute SQL query"
      }
    }
  ],
  "intermediate_data": [
    {
      "tool_name": "base_readQuery",
      "data": [{"database": "DEMO_DB"}]
    }
  ],
  "result": null
}
```

**Action:** Continue polling. Optionally display progress from `events`.

---

### 5.4. Status: complete

Task finished successfully. Result is available.

**Response:**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status": "complete",
  "last_updated": "2026-02-09T10:15:08Z",
  "events": [
    {
      "timestamp": "2026-02-09T10:15:08Z",
      "event_type": "token_update",
      "event_data": {
        "turn_input": 4523,
        "turn_output": 287
      }
    }
  ],
  "intermediate_data": [ ... ],
  "result": {
    "final_answer": "There are 3 databases available: DEMO_DB, ANALYTICS_DB, REPORTING_DB",
    "final_answer_text": "There are 3 databases available: DEMO_DB, ANALYTICS_DB, REPORTING_DB",
    "turn_input_tokens": 4523,
    "turn_output_tokens": 287,
    "profile_tag": "@GOGET",
    "profile_type": "tool_enabled",
    "turn_id": "turn-20260209-101508"
  }
}
```

**Action:** Extract `result` object and process.

---

### 5.5. Status: error

Task execution failed.

**Response:**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status": "error",
  "last_updated": "2026-02-09T10:15:06Z",
  "events": [
    {
      "timestamp": "2026-02-09T10:15:06Z",
      "event_type": "error",
      "event_data": {
        "message": "MCP server connection failed: Database 'INVALID_DB' not found",
        "phase": 1
      }
    }
  ],
  "intermediate_data": [],
  "result": {
    "error": "Query execution failed",
    "details": "Database 'INVALID_DB' not found"
  }
}
```

**Action:** Handle error, optionally notify user.

---

### 5.6. n8n Polling Loop Configuration

**Loop Structure:**
```
Loop Over Items Node:
  Condition:
    {{$('Poll State').item.json.status}} !== "complete"
    AND
    {{$('Poll State').item.json.status}} !== "error"
    AND
    {{$('Poll State').item.json.poll_count}} < 30
```

**Inside Loop:**

**1. Wait Node:**
```
Wait Time: 2 seconds
Resume: Webhook Call (automatic)
```

**2. HTTP Request Node:**
```
Node Name: Poll Task Status
Method: GET
URL: http://localhost:5050/api/v1/tasks/{{$('Poll State').item.json.task_id}}
Authentication: Uderia API Token
```

**3. Set Node (Update Poll State):**
```
Values to Set:
  status: {{$json.status}}
  poll_count: {{$('Poll State').item.json.poll_count + 1}}
  result: {{$json.result}}
  last_updated: {{$json.last_updated}}
```

**4. If Node (Check Completion):**
```
Condition:
  {{$json.status}} equals "complete"
  OR
  {{$json.status}} equals "error"

True → Exit Loop
False → Continue Loop
```

---

### 5.7. Cancel Task (Optional)

Cancel a running task.

**Endpoint:** `POST /api/v1/tasks/{task_id}/cancel`
**Authentication:** Required

**Request:**
```http
POST http://localhost:5050/api/v1/tasks/task-9876-5432-1098-7654/cancel
Authorization: Bearer tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
```

**Response (200 OK):**
```json
{
  "status": "success",
  "message": "Cancellation request sent."
}
```

---

## 6. Response Schemas

### 6.1. Common Fields (All Profile Types)

These fields exist in **every result object** regardless of profile type:

| Field | Type | Description | Always Present |
|-------|------|-------------|----------------|
| `final_answer` | string | Complete response (HTML or text) | ✅ |
| `final_answer_text` | string | Plain text version (preferred) | ✅ |
| `turn_input_tokens` | integer | LLM input tokens | ✅ |
| `turn_output_tokens` | integer | LLM output tokens | ✅ |
| `profile_tag` | string | Profile identifier (e.g., "@GOGET") | ✅ |
| `profile_type` | string | Classification | ✅ |
| `turn_id` | string | Unique turn identifier | ✅ |

**Profile Types:**
- `tool_enabled` - Planner/Executor with MCP tools
- `llm_only` - Direct LLM conversation
- `rag_focused` - Knowledge repository search
- `genie` - Multi-profile coordinator

**n8n Extraction (Profile-Agnostic):**
```javascript
const result = $input.item.json.result;

return {
  json: {
    // Core fields (always available)
    answer: result.final_answer_text || result.final_answer,
    profile: result.profile_tag,
    type: result.profile_type,

    // Token tracking
    tokens_in: result.turn_input_tokens || 0,
    tokens_out: result.turn_output_tokens || 0,
    tokens_total: (result.turn_input_tokens || 0) + (result.turn_output_tokens || 0),

    // Metadata
    turn_id: result.turn_id,
    timestamp: new Date().toISOString()
  }
};
```

---

### 6.2. Profile-Specific Fields

These fields only exist for specific profile types:

**tool_enabled Only:**
- `execution_trace[]` - Plan phases and tool calls
- `original_plan{}` - Strategic meta-plan
- `collected_data{}` - Tool outputs per phase

**rag_focused Only:**
- `knowledge_events[]` - Retrieved documents
- `knowledge_retrieval_event{}` - Retrieval metadata
- `knowledge_chunks_ui[]` - Full document chunks

**genie Only:**
- `genie_coordination` - Boolean flag
- `genie_events[]` - Coordination flow
- `slave_sessions{}` - Child session IDs

**Phase 1 Recommendation:** Ignore profile-specific fields and use only common fields.

---

### 6.3. Cost Calculation

Calculate query cost using common token fields:

```javascript
const result = $input.item.json.result;
const inputTokens = result.turn_input_tokens || 0;
const outputTokens = result.turn_output_tokens || 0;

// Pricing (example for Claude Sonnet 4)
const inputCostPer1k = 0.003;  // $0.003 per 1K input tokens
const outputCostPer1k = 0.015; // $0.015 per 1K output tokens

const inputCost = (inputTokens / 1000) * inputCostPer1k;
const outputCost = (outputTokens / 1000) * outputCostPer1k;
const totalCost = inputCost + outputCost;

return {
  json: {
    tokens: {
      input: inputTokens,
      output: outputTokens,
      total: inputTokens + outputTokens
    },
    cost: {
      input_usd: inputCost.toFixed(4),
      output_usd: outputCost.toFixed(4),
      total_usd: totalCost.toFixed(4)
    }
  }
};
```

---

## 7. Error Handling

### 7.1. Common Error Codes

| Code | Meaning | Cause | Solution |
|------|---------|-------|----------|
| 401 | Unauthorized | Invalid or expired token | Regenerate access token |
| 400 | Bad Request | No default profile configured | Configure profile in UI |
| 404 | Not Found | Session/task doesn't exist | Create new session |
| 503 | Service Unavailable | MCP server down or profile incomplete | Check server status |
| 429 | Too Many Requests | Rate limit exceeded | Wait and retry |

---

### 7.2. Error Response Format

**Standard Error:**
```json
{
  "error": "Human-readable error message",
  "status": "error"
}
```

**Detailed Error (with context):**
```json
{
  "error": "No default profile configured for this user",
  "details": "Please configure a profile (LLM + MCP Server combination) in the Configuration panel first.",
  "status": "error"
}
```

---

### 7.3. n8n Error Handling Strategies

**Pattern 1: Stop on Error (Development)**
```
HTTP Request Node:
  Continue On Fail: OFF

Workflow stops immediately on any HTTP error
```

**Pattern 2: Continue on Error (Production)**
```
HTTP Request Node:
  Continue On Fail: ON

Add If Node after:
  Condition: {{$json.error}} exists
  True → Error handling path
  False → Success path
```

**Pattern 3: Retry with Backoff**
```javascript
const retryCount = $('Error State').item.json.retry_count || 0;
const maxRetries = 3;

if (retryCount < maxRetries) {
  const backoff = Math.pow(2, retryCount) * 1000; // 1s, 2s, 4s
  await new Promise(resolve => setTimeout(resolve, backoff));

  return {
    json: {
      should_retry: true,
      retry_count: retryCount + 1
    }
  };
}

return {
  json: {
    should_retry: false,
    error: "Max retries exceeded"
  }
};
```

---

### 7.4. Specific Error Scenarios

**Error: 401 Unauthorized**

**Cause:** Access token expired or invalid

**Solution:**
```javascript
// Check token expiry before each request
const staticData = this.getWorkflowStaticData('global');
const expiresAt = new Date(staticData.token_expires_at);
const now = new Date();

if (now >= expiresAt) {
  // Token expired, regenerate
  throw new Error("Token expired. Please regenerate access token.");
}
```

**Error: 400 Bad Request - No Default Profile**

**Cause:** User has no default profile configured

**Solution:**
1. Login to Uderia UI
2. Navigate: Setup → Profiles
3. Create profile (or select existing)
4. Click "Set as Default"
5. Retry n8n workflow

**Error: 404 Not Found - Session**

**Cause:** Session expired (24-hour inactivity) or invalid session_id

**Solution:**
```javascript
// Retry with new session
const response = await fetch('http://localhost:5050/api/v1/sessions', {
  method: 'POST',
  headers: {'Authorization': `Bearer ${token}`}
});

const {session_id} = await response.json();
// Use new session_id
```

---

## 8. n8n-Specific Tips

### 8.1. Variable References

**Accessing Previous Node Data:**
```javascript
// Reference output from specific node
{{$('Node Name').item.json.field_name}}

// Examples:
{{$('Create Session').item.json.session_id}}
{{$('Poll Task').item.json.result.final_answer}}
{{$('Store Token').item.json.access_token}}
```

**Accessing Current Node Input:**
```javascript
// In Code node
const inputData = $input.item.json;
const sessionId = inputData.session_id;
```

**JSON Path Expressions:**
```javascript
// Deep nested access
{{$json.result.execution_trace[0].tool_name}}
{{$json.events[0].event_data.message}}

// With fallback
{{$json.result.final_answer_text || $json.result.final_answer}}
```

---

### 8.2. Workflow Static Data

**Persist data across workflow executions:**

```javascript
// Store (survives workflow runs)
const staticData = this.getWorkflowStaticData('global');
staticData.access_token = 'tda_123...';
staticData.session_id = 'session-abc...';
staticData.token_expires_at = '2026-05-10T10:00:00Z';

// Retrieve in next execution
const token = this.getWorkflowStaticData('global').access_token;
```

**Use Cases:**
- Token caching (avoid re-authentication)
- Session reuse (multi-turn conversations)
- Usage tracking (count API calls)

---

### 8.3. Credential Management

**Creating Reusable Credentials:**
```
1. n8n → Settings → Credentials → New
2. Type: Header Auth
3. Name: Uderia API Token
4. Header Name: Authorization
5. Header Value: Bearer tda_YOUR_TOKEN
6. Save

Use in ALL HTTP Request nodes to Uderia
```

**Environment-Specific Credentials:**
```
Development: Uderia API Token (Dev)
Production: Uderia API Token (Prod)

Select appropriate credential in HTTP Request nodes
```

---

### 8.4. Polling Loop Best Practices

**Efficient Loop Structure:**
```
Loop Node:
  Condition: status !== "complete" AND status !== "error" AND poll_count < 30

Inside Loop:
  1. Wait 2 seconds
  2. HTTP Request: Poll status
  3. Set: Update status, increment poll_count
  4. If: status complete → Exit Loop
```

**Adaptive Polling Intervals:**
```javascript
// Adjust wait time based on poll count
const pollCount = $('Poll State').item.json.poll_count;

let waitMs = 2000; // Default 2 seconds
if (pollCount > 10) waitMs = 3000;  // After 20s, slow to 3s
if (pollCount > 20) waitMs = 5000;  // After 60s, slow to 5s

return { wait_ms: waitMs };
```

**Early Exit on Completion:**
```javascript
// Check status and exit immediately
const status = $json.status;

if (status === "complete" || status === "error") {
  return {
    json: {
      status,
      should_continue: false,
      result: $json.result
    }
  };
}

return {
  json: {
    status,
    should_continue: true,
    poll_count: $('Poll State').item.json.poll_count + 1
  }
};
```

---

## 9. Code Snippets Library

### 9.1. Complete Query Workflow (JavaScript)

```javascript
// Complete workflow in a single Code node (for reference)
const BASE_URL = 'http://localhost:5050';
const TOKEN = 'tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p';

// 1. Create Session
const sessionResp = await fetch(`${BASE_URL}/api/v1/sessions`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${TOKEN}`
  }
});
const {session_id} = await sessionResp.json();

// 2. Submit Query
const queryResp = await fetch(`${BASE_URL}/api/v1/sessions/${session_id}/query`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${TOKEN}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    prompt: 'Show me all databases'
  })
});
const {task_id} = await queryResp.json();

// 3. Poll for Results
let status, result;
for (let i = 0; i < 30; i++) {
  await new Promise(resolve => setTimeout(resolve, 2000)); // Wait 2s

  const taskResp = await fetch(`${BASE_URL}/api/v1/tasks/${task_id}`, {
    headers: {'Authorization': `Bearer ${TOKEN}`}
  });
  const taskData = await taskResp.json();

  status = taskData.status;
  result = taskData.result;

  if (status === 'complete' || status === 'error') break;
}

// 4. Return Result
return {
  json: {
    final_answer: result.final_answer_text || result.final_answer,
    tokens_in: result.turn_input_tokens,
    tokens_out: result.turn_output_tokens,
    profile: result.profile_tag
  }
};
```

---

### 9.2. Token Expiry Check

```javascript
// Check if access token is close to expiry
const staticData = this.getWorkflowStaticData('global');
const expiresAt = staticData.token_expires_at || 0;
const now = Date.now();
const hoursUntilExpiry = (expiresAt - now) / (1000 * 60 * 60);

if (hoursUntilExpiry < 24) {
  // Token expires within 24 hours, regenerate
  return {
    json: {
      action: 'regenerate_token',
      expires_in_hours: hoursUntilExpiry.toFixed(1)
    }
  };
}

return {
  json: {
    action: 'continue',
    expires_in_hours: hoursUntilExpiry.toFixed(1)
  }
};
```

---

### 9.3. Dynamic Profile Selection

```javascript
// Select profile based on query characteristics
const query = $json.prompt.toLowerCase();
const queryLength = query.split(' ').length;

let profileId = null; // Use default

// Route by complexity
if (queryLength > 50 || query.includes('explain') || query.includes('analyze')) {
  profileId = 'profile-gpt4-thinker'; // Expensive, detailed
} else if (query.includes('list') || query.includes('show') || query.includes('get')) {
  profileId = 'profile-gemini-fast'; // Cheap, fast
}

// Route by domain
if (query.includes('mongodb') || query.includes('document')) {
  profileId = 'profile-mongodb-connector';
} else if (query.includes('postgres') || query.includes('sql')) {
  profileId = 'profile-postgres-connector';
}

return {
  json: {
    prompt: $json.prompt,
    profile_id: profileId,
    routing_reason: profileId ? 'custom' : 'default'
  }
};
```

---

### 9.4. Batch Query Processing

```javascript
// Submit multiple queries in parallel
const queries = [
  'List all databases',
  'Count total users',
  'Show recent orders'
];

const sessionId = $('Create Session').item.json.session_id;
const token = 'tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p';

// Submit all queries
const taskIds = await Promise.all(
  queries.map(async (prompt) => {
    const resp = await fetch(
      `http://localhost:5050/api/v1/sessions/${sessionId}/query`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({prompt})
      }
    );
    const {task_id} = await resp.json();
    return {prompt, task_id};
  })
);

return {json: {tasks: taskIds}};
```

---

## 10. Troubleshooting Guide

### 10.1. Authentication Failures

**Symptom:** 401 Unauthorized errors

**Checks:**
1. Verify token format: `tda_*` (32 characters)
2. Check token expiry in Uderia UI: Administration → Access Tokens
3. Verify `Authorization` header: `Bearer tda_...`
4. Test token with curl:
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://localhost:5050/api/v1/sessions
   ```

**Solution:** Regenerate access token and update n8n credentials.

---

### 10.2. Session Creation Fails

**Symptom:** 400 Bad Request - "No default profile configured"

**Checks:**
1. Login to Uderia UI
2. Navigate: Setup → Profiles
3. Verify at least one profile exists
4. Check "Is Default" column

**Solution:**
1. Create profile (LLM + MCP Server)
2. Click "Set as Default" button
3. Retry n8n workflow

**API Check:**
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:5050/api/v1/profiles | jq '.[] | select(.is_default==true)'
```

---

### 10.3. Polling Timeout

**Symptom:** Workflow exits loop before result received

**Causes:**
- Query takes >60 seconds (30 polls × 2s)
- Complex database operations
- Large result sets

**Solutions:**

1. **Increase max polls:**
   ```javascript
   max_polls: 60  // 120 seconds instead of 60
   ```

2. **Adjust polling interval:**
   ```javascript
   waitMs: 3000  // 3 seconds instead of 2
   ```

3. **Check actual query duration:**
   ```bash
   # Monitor Uderia logs
   tail -f /tmp/uderia_server.log | grep "Task completed"
   ```

---

### 10.4. Result Parsing Issues

**Symptom:** Cannot extract `final_answer` or tokens

**Checks:**
1. Verify result is not null:
   ```javascript
   if (!$json.result) {
     throw new Error('Result is null, task may not be complete');
   }
   ```

2. Check profile type:
   ```javascript
   const profileType = $json.result.profile_type;
   console.log('Profile type:', profileType);
   ```

3. Use fallback extraction:
   ```javascript
   const answer = $json.result.final_answer_text
               || $json.result.final_answer
               || 'No answer available';
   ```

---

### 10.5. MCP Server Connection Errors

**Symptom:** 503 Service Unavailable or task returns error

**Checks:**
1. Check MCP server status in Uderia UI: Setup → MCP Servers
2. Verify MCP server is running:
   ```bash
   # Check server logs
   grep "MCP server initialized" /tmp/uderia_server.log
   ```

3. Test MCP connectivity:
   - Submit simple query via UI
   - Check if error is consistent

**Solutions:**
- Restart MCP server
- Verify MCP server configuration (host, port, credentials)
- Check firewall rules if MCP server is remote

---

### 10.6. Session Not Found (404)

**Symptom:** Query submission returns 404 Not Found

**Causes:**
- Session expired (24-hour inactivity)
- Invalid session_id
- Session deleted

**Solution:**
```javascript
// Retry with new session
try {
  // Try existing session
  const resp = await fetch(`http://localhost:5050/api/v1/sessions/${sessionId}/query`, ...);
  if (resp.status === 404) {
    throw new Error('Session not found');
  }
} catch (error) {
  // Create new session
  const newSession = await fetch('http://localhost:5050/api/v1/sessions', {
    method: 'POST',
    headers: {'Authorization': `Bearer ${token}`}
  });
  const {session_id} = await newSession.json();
  // Use new session_id
}
```

---

### 10.7. Rate Limiting (429)

**Symptom:** 429 Too Many Requests

**Rate Limits:**
- Registration: 3 per hour per IP
- Login: 5 attempts per minute per IP
- API calls: User-specific quotas (if enabled)

**Solution:**
1. Wait before retrying (check `Retry-After` header)
2. Implement exponential backoff
3. Contact admin to adjust rate limits

---

## 11. Quick Reference Card

### Essential Endpoints

```
POST /auth/login                              → Get JWT
POST /api/v1/auth/tokens                      → Create access token
POST /api/v1/sessions                         → Create session
POST /api/v1/sessions/{id}/query              → Submit query
GET  /api/v1/tasks/{id}                       → Poll status
```

### Polling Strategy

```
Interval: 2 seconds
Max Polls: 30 (60 seconds)
Exit: status === "complete" || status === "error"
```

### Common Fields (All Profiles)

```javascript
result.final_answer_text    // Plain text answer
result.turn_input_tokens    // Input tokens
result.turn_output_tokens   // Output tokens
result.profile_tag          // Profile identifier
result.profile_type         // Profile classification
```

### Error Codes

```
401 → Token invalid (regenerate)
400 → No default profile (configure in UI)
404 → Session not found (create new)
503 → MCP server down (check status)
```

---

**End of API Reference**

For additional help:
- See [QUICKSTART.md](QUICKSTART.md) for first workflow tutorial
- See [WORKFLOW_TEMPLATES.md](WORKFLOW_TEMPLATES.md) for complete examples
- Report issues: https://github.com/anthropics/claude-code/issues
