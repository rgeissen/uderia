# Uderia + n8n Quick Start Guide

**Goal:** Execute your first Uderia query from n8n in under 10 minutes.

**What You'll Build:** A simple manual workflow that creates a session, submits a query, polls for results, and displays the answer.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Authentication Setup](#2-authentication-setup)
3. [Core Concepts](#3-core-concepts)
4. [Your First n8n Workflow](#4-your-first-n8n-workflow)
5. [Common Pitfalls & Solutions](#5-common-pitfalls--solutions)
6. [Next Steps](#6-next-steps)

---

## 1. Prerequisites

Before starting, ensure you have:

### 1.1. Uderia Platform Running

**Local Installation:**
```bash
# Check if Uderia is running
curl http://localhost:5050/health

# Expected: {"status": "healthy"}
```

**Remote Server:**
- Access to Uderia instance (e.g., `http://uderia.company.com:5050`)
- Network connectivity from n8n to Uderia

### 1.2. n8n Installed

**Options:**
- **n8n Cloud** - https://n8n.io/cloud
- **Self-Hosted** - https://docs.n8n.io/hosting/
- **Desktop App** - https://n8n.io/desktop

**Verify n8n is running:**
- Access n8n web interface (e.g., `http://localhost:5678`)
- Create a new workflow

### 1.3. Uderia Account & Profile

**Required Setup:**

1. **User Account**
   - Register at Uderia UI: `http://localhost:5050`
   - Default credentials (first install): `admin` / `admin`

2. **Default Profile Configured** ⚠️ **CRITICAL**
   - Navigate: **Setup → Profiles**
   - Create profile (LLM + MCP Server combination)
   - Click **"Set as Default"** button
   - Without this, API calls will fail with `400 Bad Request`

3. **Test Profile**
   - Submit a query via Uderia UI
   - Verify you get a response
   - This confirms LLM and MCP server are working

---

## 2. Authentication Setup

### 2.1. Obtaining an Access Token

n8n automation requires a **long-lived access token** (not a JWT).

**Step 1: Login to Get JWT**

```bash
# Login to Uderia
curl -X POST http://localhost:5050/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your_password"}' \
  | jq -r '.token'

# Output: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

Copy the JWT token (starts with `eyJ`).

**Step 2: Create Access Token**

```bash
JWT="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

curl -X POST http://localhost:5050/api/v1/auth/tokens \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "n8n Integration",
    "expires_in_days": 90
  }' | jq -r '.token'

# Output: tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
```

⚠️ **CRITICAL:** Copy the `tda_*` token immediately! It's shown only once.

**Token Lifetime:**
- `30`, `60`, `90`, `180`, `365` days, or `0` (never expires)
- For production automation, use `0` (never expires)

---

### 2.2. Storing Credentials in n8n

**Step 1: Create Credential**

1. Open n8n web interface
2. Navigate: **Settings → Credentials → New**
3. Search: **"Header Auth"**
4. Click: **"Header Auth"**

**Step 2: Configure Credential**

```
Credential Name: Uderia API Token
Header Name: Authorization
Header Value: Bearer tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
```

**Important:** Include the word `Bearer` followed by a space, then the token.

**Step 3: Save Credential**

Click **"Create"** button. This credential will be reused across all Uderia HTTP Request nodes.

---

### 2.3. Token Lifecycle Management

**Token Expiry:**
- Check token status: **Uderia UI → Administration → Access Tokens**
- View expiration date in `expires_at` column

**Token Revocation:**
```bash
# List tokens
curl -X GET http://localhost:5050/api/v1/auth/tokens \
  -H "Authorization: Bearer $JWT" | jq

# Revoke token
curl -X DELETE http://localhost:5050/api/v1/auth/tokens/{token_id} \
  -H "Authorization: Bearer $JWT"
```

**Regeneration Strategy:**
- If token expires → Regenerate using Step 2.1 above
- Update n8n credential with new token
- All workflows automatically use new token

---

## 3. Core Concepts

### 3.1. The Three-Step Pattern

Every Uderia query from n8n follows this pattern:

```
┌─────────────────┐
│  STEP 1:        │
│  Create Session │ → Returns: session_id
└─────────────────┘
        ↓
┌─────────────────┐
│  STEP 2:        │
│  Submit Query   │ → Returns: task_id
└─────────────────┘
        ↓
┌─────────────────┐
│  STEP 3:        │
│  Poll Results   │ → Returns: result object
└─────────────────┘
```

**Why Asynchronous?**
- AI agent operations can take 5-60+ seconds
- Polling avoids timeouts and connection issues
- Enables parallel query processing

---

### 3.2. Profile System Overview

**What is a Profile?**
- Combines **LLM Provider** (e.g., Claude, GPT-4, Gemini) + **MCP Server** (data source)
- Defines query execution strategy (tool-enabled, conversation, RAG, Genie)

**Profile Types:**

| Type | Description | Use Case |
|------|-------------|----------|
| **tool_enabled** | Planner/Executor with strategic planning | Complex database queries, multi-step workflows |
| **llm_only** | Direct LLM conversation | Simple chat, lightweight Q&A |
| **rag_focused** | Knowledge repository search | Documentation lookup, reference search |
| **genie** | Multi-profile coordinator | Complex questions requiring multiple experts |

**Profile Tags:**
- Each profile has a tag (e.g., `@GOGET`, `@CHAT`, `@FOCUS`)
- Tags can be used in UI with `@TAG` syntax
- REST API uses `profile_id` parameter

**Default Profile:**
- Used automatically if no override specified
- Set in Uderia UI: **Setup → Profiles → Set as Default**

---

### 3.3. Session Isolation

**Sessions** provide isolated conversation contexts:

- Each session maintains independent history
- Multi-turn conversations work within a session
- Sessions expire after **24 hours of inactivity**

**Session Reuse (Optional):**
```javascript
// Create once
const sessionId = 'a1b2c3d4-e5f6-7890-1234-567890abcdef';

// Query 1
POST /api/v1/sessions/{sessionId}/query
Body: {"prompt": "List databases"}

// Query 2 (reuses context)
POST /api/v1/sessions/{sessionId}/query
Body: {"prompt": "Show tables in the first one"}
```

**For Quick Start:** Create new session per workflow execution (simpler).

---

### 3.4. Task Polling Strategy

**Polling Loop Configuration:**

```
Interval: 2 seconds
Max Attempts: 30 (60 seconds total)
Exit Condition: status === "complete" OR status === "error"
```

**Status Values:**

| Status | Meaning | Action |
|--------|---------|--------|
| `pending` | Task queued, not started | Keep polling |
| `processing` | Execution in progress | Keep polling |
| `complete` | Finished successfully ✅ | Extract result |
| `error` | Execution failed ❌ | Handle error |
| `cancelled` | User cancelled | Handle cancellation |

**Why 2 Seconds?**
- Balances responsiveness vs server load
- Matches Uderia's internal polling patterns
- Most queries complete within 10-20 seconds (5-10 polls)

---

## 4. Your First n8n Workflow

### 4.1. Workflow Overview

We'll build a **12-node workflow** that:
1. Triggers manually
2. Creates a Uderia session
3. Submits a query: "List all databases"
4. Polls for completion (up to 60 seconds)
5. Extracts the final answer
6. Displays token usage and result

**Architecture:**
```
Manual Trigger → Create Session → Submit Query → Poll Loop
                                                      ↓
                                Display Result ← Extract Answer
```

**Estimated Build Time:** 10 minutes

---

### 4.2. Create New Workflow

1. Open n8n web interface
2. Click: **"New workflow"**
3. Workflow Name: **"Uderia Quick Start"**

---

### 4.3. Node 1: Manual Trigger

**Purpose:** Start the workflow on demand.

**Steps:**
1. n8n automatically adds a **Manual Trigger** node
2. No configuration needed
3. This node initiates the workflow when you click **"Execute Workflow"**

**Visual Indicator:** Gray play button icon

---

### 4.4. Node 2: HTTP Request - Create Session

**Purpose:** Create a new Uderia conversation session.

**Steps:**

1. Click **"+"** next to Manual Trigger
2. Search: **"HTTP Request"**
3. Select: **"HTTP Request"**

**Configuration:**

```
Node Name: Create Session

Method: POST
URL: http://localhost:5050/api/v1/sessions

Authentication:
  ✅ Use Credential
  Credential Type: Header Auth
  Credential: Uderia API Token (created in Section 2.2)

Options → Response:
  Response Format: JSON
  Full Response: OFF
```

**Test the Node:**
1. Click: **"Execute node"**
2. Expected Output:
   ```json
   {
     "session_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef"
   }
   ```

**Common Errors:**

| Error | Cause | Solution |
|-------|-------|----------|
| 401 Unauthorized | Invalid token | Check credential, regenerate token |
| 400 Bad Request | No default profile | Configure profile in Uderia UI |
| Connection refused | Uderia not running | Start Uderia server |

---

### 4.5. Node 3: Set - Store Session Context

**Purpose:** Save the session ID for use in subsequent nodes.

**Steps:**

1. Click **"+"** after Create Session
2. Search: **"Set"**
3. Select: **"Set"**

**Configuration:**

```
Node Name: Store Session Context

Mode: Manual Mapping

Values to Set:
  1. Name: session_id
     Value: {{$json.session_id}}

  2. Name: created_at
     Value: {{$now}}
```

**Visual Check:**
- Should see `session_id` and `created_at` in output data

---

### 4.6. Node 4: HTTP Request - Submit Query

**Purpose:** Submit a natural language query to the session.

**Steps:**

1. Click **"+"** after Store Session Context
2. Search: **"HTTP Request"**
3. Select: **"HTTP Request"**

**Configuration:**

```
Node Name: Submit Query

Method: POST
URL: http://localhost:5050/api/v1/sessions/{{$('Store Session Context').item.json.session_id}}/query

Authentication:
  ✅ Use Credential
  Credential: Uderia API Token

Send Body: ON
Body Content Type: JSON
Specify Body: JSON

Body (JSON):
{
  "prompt": "List all databases available on the system"
}

Options → Response:
  Response Format: JSON
```

**Important:** The URL uses an expression `{{$('Store Session Context').item.json.session_id}}` to reference the session ID from Node 3.

**Test the Node:**
1. Click: **"Execute node"**
2. Expected Output:
   ```json
   {
     "task_id": "task-9876-5432-1098-7654",
     "status_url": "/api/v1/tasks/task-9876-5432-1098-7654"
   }
   ```

---

### 4.7. Node 5: Set - Initialize Poll State

**Purpose:** Set up variables for the polling loop.

**Steps:**

1. Click **"+"** after Submit Query
2. Search: **"Set"**
3. Select: **"Set"**

**Configuration:**

```
Node Name: Initialize Poll State

Mode: Manual Mapping

Values to Set:
  1. Name: task_id
     Value: {{$json.task_id}}

  2. Name: status
     Value: pending

  3. Name: poll_count
     Value: 0

  4. Name: max_polls
     Value: 30

  5. Name: result
     Value: null
```

**Purpose of Each Field:**
- `task_id`: The task to poll
- `status`: Current task status (starts as "pending")
- `poll_count`: Number of poll attempts (starts at 0)
- `max_polls`: Maximum attempts before timeout (30 = 60 seconds)
- `result`: Stores final result (null until complete)

---

### 4.8. Polling Loop (Nodes 6-9)

**Purpose:** Poll task status every 2 seconds until completion or timeout.

This is the most complex part of the workflow. We'll build it step by step.

---

#### Node 6: Loop Over Items

**Purpose:** Create a loop that runs while the task is not complete.

**Steps:**

1. Click **"+"** after Initialize Poll State
2. Search: **"Loop Over Items"**
3. Select: **"Loop Over Items"**

**Configuration:**

```
Node Name: Poll Loop

Mode: Run Once for Each Item

Max Iterations: 30
```

**Loop Condition:**
```
{{$('Initialize Poll State').item.json.status}} !== "complete"
AND
{{$('Initialize Poll State').item.json.status}} !== "error"
AND
{{$('Initialize Poll State').item.json.poll_count}} < {{$('Initialize Poll State').item.json.max_polls}}
```

**Explanation:**
- Continue looping while status is NOT "complete" or "error"
- AND poll_count hasn't exceeded max_polls (30)

---

#### Inside the Loop: Node 7 - Wait

**Purpose:** Wait 2 seconds between polls.

**Steps:**

1. Click **"+"** inside the Poll Loop (dotted box)
2. Search: **"Wait"**
3. Select: **"Wait"**

**Configuration:**

```
Node Name: Wait 2 Seconds

Wait: 2 seconds
Resume: Webhook Call (default)
```

**Why Wait?**
- Prevents overwhelming the server with rapid requests
- Standard polling interval (matches Uderia's internal patterns)

---

#### Inside the Loop: Node 8 - HTTP Request - Check Status

**Purpose:** Poll the task status endpoint.

**Steps:**

1. Click **"+"** after Wait 2 Seconds
2. Search: **"HTTP Request"**
3. Select: **"HTTP Request"**

**Configuration:**

```
Node Name: Poll Task Status

Method: GET
URL: http://localhost:5050/api/v1/tasks/{{$('Initialize Poll State').item.json.task_id}}

Authentication:
  ✅ Use Credential
  Credential: Uderia API Token

Options → Response:
  Response Format: JSON
```

**Expected Output (processing):**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status": "processing",
  "last_updated": "2026-02-09T10:15:05Z",
  "events": [...],
  "result": null
}
```

**Expected Output (complete):**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status": "complete",
  "last_updated": "2026-02-09T10:15:08Z",
  "events": [...],
  "result": {
    "final_answer": "There are 3 databases: DEMO_DB, ANALYTICS_DB, REPORTING_DB",
    "final_answer_text": "There are 3 databases: DEMO_DB, ANALYTICS_DB, REPORTING_DB",
    "turn_input_tokens": 4523,
    "turn_output_tokens": 287,
    "profile_tag": "@GOGET",
    "profile_type": "tool_enabled"
  }
}
```

---

#### Inside the Loop: Node 9 - Set - Update Poll State

**Purpose:** Update loop variables with new status and increment poll count.

**Steps:**

1. Click **"+"** after Poll Task Status
2. Search: **"Set"**
3. Select: **"Set"**

**Configuration:**

```
Node Name: Update Poll State

Mode: Manual Mapping

Values to Set:
  1. Name: task_id
     Value: {{$('Initialize Poll State').item.json.task_id}}

  2. Name: status
     Value: {{$json.status}}

  3. Name: poll_count
     Value: {{$('Initialize Poll State').item.json.poll_count + 1}}

  4. Name: max_polls
     Value: {{$('Initialize Poll State').item.json.max_polls}}

  5. Name: result
     Value: {{$json.result}}

  6. Name: last_updated
     Value: {{$json.last_updated}}
```

**Key Update:**
- `status`: Updated from API response
- `poll_count`: Incremented by 1 each iteration
- `result`: Captured from API (null until complete)

**Loop Exit:**
- When `status` becomes "complete" or "error", loop exits
- OR when `poll_count` reaches `max_polls` (timeout)

---

### 4.9. Node 10: Switch - Route by Status

**Purpose:** Route workflow based on final status (success/error/timeout).

**Steps:**

1. Click **"+"** after Poll Loop (outside the dotted box)
2. Search: **"Switch"**
3. Select: **"Switch"**

**Configuration:**

```
Node Name: Route by Status

Mode: Rules

Rules:
  1. If: {{$('Update Poll State').item.json.status}} equals "complete"
     Output: 0

  2. If: {{$('Update Poll State').item.json.status}} equals "error"
     Output: 1

  3. Otherwise
     Output: 2
```

**Routing:**
- **Output 0** → Success path (status is "complete")
- **Output 1** → Error path (status is "error")
- **Output 2** → Timeout path (neither complete nor error)

---

### 4.10. Node 11: Code - Extract Answer (Success Path)

**Purpose:** Extract final answer and token counts from result.

**Steps:**

1. Click **"+"** from Switch **Output 0**
2. Search: **"Code"**
3. Select: **"Code"**

**Configuration:**

```
Node Name: Extract Answer

Mode: Run Once for All Items

Code (JavaScript):
```

```javascript
// Extract result from task response
const taskData = $input.item.json;
const result = taskData.result;

// Handle missing result
if (!result) {
  return {
    json: {
      error: true,
      message: "No result found in task response",
      status: taskData.status
    }
  };
}

// Profile-agnostic field extraction
const finalAnswer = result.final_answer_text || result.final_answer || "No answer provided";

return {
  json: {
    // Core fields (available in all profiles)
    final_answer: finalAnswer,
    profile_tag: result.profile_tag || "unknown",
    profile_type: result.profile_type || "unknown",

    // Token tracking
    input_tokens: result.turn_input_tokens || 0,
    output_tokens: result.turn_output_tokens || 0,
    total_tokens: (result.turn_input_tokens || 0) + (result.turn_output_tokens || 0),

    // Metadata
    turn_id: result.turn_id,
    poll_count: taskData.poll_count,

    // Timestamps
    started_at: taskData.created_at,
    completed_at: new Date().toISOString()
  }
};
```

**Expected Output:**
```json
{
  "final_answer": "There are 3 databases available: DEMO_DB, ANALYTICS_DB, REPORTING_DB",
  "profile_tag": "@GOGET",
  "profile_type": "tool_enabled",
  "input_tokens": 4523,
  "output_tokens": 287,
  "total_tokens": 4810,
  "turn_id": "turn-20260209-101508",
  "poll_count": 5
}
```

---

### 4.11. Node 12: Stop and Error (Optional Paths)

**Error Path (Switch Output 1):**

1. Click **"+"** from Switch **Output 1**
2. Search: **"Stop and Error"**
3. Select: **"Stop and Error"**

**Configuration:**
```
Node Name: Handle Error

Error Message:
  Query failed: {{$('Update Poll State').item.json.result.error || 'Unknown error'}}
```

**Timeout Path (Switch Output 2):**

1. Click **"+"** from Switch **Output 2**
2. Search: **"Stop and Error"**
3. Select: **"Stop and Error"**

**Configuration:**
```
Node Name: Handle Timeout

Error Message:
  Query timed out after {{$('Update Poll State').item.json.poll_count}} polls ({{$('Update Poll State').item.json.poll_count * 2}} seconds)
```

---

### 4.12. Final Workflow Structure

Your workflow should now have **12 nodes**:

```
1. Manual Trigger
2. Create Session (HTTP Request)
3. Store Session Context (Set)
4. Submit Query (HTTP Request)
5. Initialize Poll State (Set)
6. Poll Loop (Loop Over Items)
   ├─ 7. Wait 2 Seconds (Wait)
   ├─ 8. Poll Task Status (HTTP Request)
   └─ 9. Update Poll State (Set)
10. Route by Status (Switch)
    ├─ 11. Extract Answer (Code) - Output 0
    ├─ 12. Handle Error (Stop and Error) - Output 1
    └─ 13. Handle Timeout (Stop and Error) - Output 2
```

---

### 4.13. Save and Test

**Save Workflow:**
1. Click: **Ctrl+S** (or Cmd+S on Mac)
2. Workflow Name: **"Uderia Quick Start"**
3. Click: **"Save"**

**Execute Workflow:**
1. Click: **"Execute Workflow"** button (top right)
2. Watch nodes light up green as they execute
3. Final node (Extract Answer) should display result

**Expected Execution Time:** 10-20 seconds (depends on query complexity)

**Success Indicators:**
- ✅ All nodes green
- ✅ Extract Answer node shows `final_answer` with database names
- ✅ `input_tokens` and `output_tokens` are non-zero
- ✅ `poll_count` is between 5-15

---

## 5. Common Pitfalls & Solutions

### 5.1. Token Expiry (401 Unauthorized)

**Symptom:** HTTP Request nodes fail with 401 status code.

**Causes:**
- Access token expired (default: 90 days)
- Token was revoked
- Token format incorrect (missing `Bearer` prefix)

**Solutions:**

1. **Check Token in Uderia UI:**
   - Navigate: **Administration → Access Tokens**
   - Verify token status and expiry date

2. **Regenerate Token:**
   ```bash
   # Re-login to get fresh JWT
   JWT=$(curl -s -X POST http://localhost:5050/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"your_password"}' | jq -r '.token')

   # Create new access token
   curl -X POST http://localhost:5050/api/v1/auth/tokens \
     -H "Authorization: Bearer $JWT" \
     -H "Content-Type: application/json" \
     -d '{"name":"n8n Integration","expires_in_days":90}' | jq -r '.token'
   ```

3. **Update n8n Credential:**
   - n8n Settings → Credentials → Uderia API Token → Edit
   - Replace `Header Value` with new token (include `Bearer` prefix)
   - Save

**Prevention:**
- Set token to **never expire** (`expires_in_days: 0`)
- Monitor token expiry in Uderia admin panel
- Set calendar reminder for token rotation

---

### 5.2. Polling Timeout

**Symptom:** Workflow hits timeout path after 30 polls (60 seconds).

**Causes:**
- Query complexity (large database, complex joins)
- LLM provider slowness (network latency)
- MCP server performance (slow data retrieval)

**Solutions:**

1. **Increase Max Polls:**
   - Edit **Initialize Poll State** node
   - Change `max_polls` from `30` to `60` (120 seconds)
   - Or `90` (180 seconds) for very complex queries

2. **Adjust Polling Interval:**
   - Edit **Wait 2 Seconds** node
   - Change from `2 seconds` to `3 seconds` (less frequent polls)
   - Trade-off: Slower feedback, but longer timeout window

3. **Check Query Duration:**
   ```bash
   # Monitor Uderia logs
   tail -f /tmp/uderia_server.log | grep "Task completed"
   ```

4. **Optimize Query:**
   - Simplify prompt (be more specific)
   - Use lighter profile (e.g., `llm_only` instead of `tool_enabled`)

**Formula:**
```
Max Wait Time = max_polls × interval

Examples:
- 30 × 2s = 60 seconds
- 60 × 2s = 120 seconds (recommended for complex queries)
- 30 × 3s = 90 seconds (alternative)
```

---

### 5.3. Profile Not Configured (400 Bad Request)

**Symptom:** Create Session fails with error:
```json
{
  "error": "No default profile configured for this user. Please configure a profile (LLM + MCP Server combination) in the Configuration panel first."
}
```

**Cause:** User account has no default profile set.

**Solution:**

1. **Login to Uderia Web UI:**
   - Navigate to: `http://localhost:5050`

2. **Check Existing Profiles:**
   - Go to: **Setup → Profiles**
   - Look for any existing profiles

3. **Create Profile (if none exist):**
   - Click: **"+ Create Profile"**
   - Select: **LLM Provider** (e.g., Google Gemini, Anthropic Claude)
   - Select: **MCP Server** (your data source)
   - Enter: Profile details
   - Click: **"Save"**

4. **Set as Default:**
   - In Profiles list, find your profile
   - Click: **"Set as Default"** button
   - Verify: **"Is Default"** column shows **✓**

5. **Test via UI:**
   - Go to: **Chat** tab
   - Submit test query: "List databases"
   - Verify you get a response

6. **Retry n8n Workflow:**
   - Execute workflow again
   - Should now succeed

**API Verification:**
```bash
# Check default profile
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/v1/profiles | jq '.[] | select(.is_default==true)'

# Expected: One profile with "is_default": true
```

---

### 5.4. MCP Server Connection Error (503)

**Symptom:** Query execution fails with:
```json
{
  "error": "MCP server connection failed"
}
```

**Causes:**
- MCP server not running
- Incorrect MCP server configuration
- Network connectivity issues

**Solutions:**

1. **Check MCP Server Status:**
   - Uderia UI: **Setup → MCP Servers**
   - Verify server is listed and "Status" shows green

2. **Check Uderia Logs:**
   ```bash
   tail -50 /tmp/uderia_server.log | grep "MCP"
   # Look for: "MCP server initialized" or connection errors
   ```

3. **Test MCP Connectivity:**
   - Submit query via Uderia UI
   - If UI also fails, MCP server issue (not n8n-specific)

4. **Restart MCP Server:**
   ```bash
   # Example for SQLite MCP server
   npx -y @modelcontextprotocol/server-sqlite /path/to/database.db
   ```

5. **Verify Profile Configuration:**
   - Uderia UI: **Setup → Profiles**
   - Check that profile's MCP Server is correct

---

### 5.5. Cannot Parse Result

**Symptom:** Extract Answer node shows error or null values.

**Causes:**
- Accessing result before task completes
- Incorrect result path
- Task returned error instead of result

**Solutions:**

1. **Verify Task Status:**
   ```javascript
   // In Extract Answer Code node, add check
   const status = $input.item.json.status;
   if (status !== 'complete') {
     throw new Error(`Task not complete. Status: ${status}`);
   }
   ```

2. **Handle Missing Result:**
   ```javascript
   const result = $input.item.json.result;
   if (!result) {
     return {
       json: {
         error: true,
         message: 'Result is null. Task may have failed.',
         status: $input.item.json.status
       }
     };
   }
   ```

3. **Use Fallback Extraction:**
   ```javascript
   const finalAnswer = result.final_answer_text
                    || result.final_answer
                    || result.html_response  // Genie profiles
                    || 'No answer available';
   ```

4. **Debug Result Structure:**
   - Click on **Poll Task Status** node
   - View output JSON
   - Verify `result` object exists and has expected fields

---

### 5.6. Expression Error in Node

**Symptom:** Node shows error: "Cannot read property 'json' of undefined".

**Causes:**
- Referencing node that hasn't executed
- Typo in node name
- Incorrect expression syntax

**Solutions:**

1. **Check Node Name:**
   - Ensure referenced node name matches exactly
   - Example: `$('Store Session Context')` must match node name

2. **Execute Previous Nodes First:**
   - Before testing a node, execute all nodes before it
   - n8n expressions reference previous node outputs

3. **Use Expression Editor:**
   - Click field to see expression editor
   - Autocomplete shows available nodes

4. **Test Expression:**
   ```javascript
   // In Code node, debug expression
   const sessionId = $('Store Session Context').item.json.session_id;
   console.log('Session ID:', sessionId);
   ```

---

### 5.7. HTTP Connection Refused

**Symptom:** HTTP Request nodes fail with "ECONNREFUSED".

**Causes:**
- Uderia server not running
- Wrong URL (port, host, protocol)
- Firewall blocking connection

**Solutions:**

1. **Verify Uderia is Running:**
   ```bash
   curl http://localhost:5050/health
   # Expected: {"status": "healthy"}
   ```

2. **Check URL in Nodes:**
   - Ensure: `http://localhost:5050` (not `https`)
   - Check port: `5050` (default)
   - If remote server: Use correct hostname/IP

3. **Test from n8n Server:**
   ```bash
   # If n8n is on different machine
   curl http://uderia-host:5050/health
   ```

4. **Check Firewall:**
   - Allow port 5050 inbound
   - Check Docker network (if using containers)

---

## 6. Next Steps

### 6.1. Import Reference Workflows

Now that you've built your first workflow, import pre-built templates:

1. See: **[WORKFLOW_TEMPLATES.md](WORKFLOW_TEMPLATES.md)**
2. Import workflows:
   - Simple Query (manual trigger)
   - Scheduled Daily Report (cron trigger)
   - Slack Integration (webhook trigger)

3. Customize for your use case:
   - Change query prompts
   - Adjust polling timeouts
   - Add output destinations (email, database, etc.)

---

### 6.2. Explore Profile Override

**Use Case:** Different queries need different LLMs or data sources.

**Implementation:**

1. **List Available Profiles:**
   ```bash
   curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:5050/api/v1/profiles | jq '.[] | {id, tag, type}'
   ```

2. **Modify Submit Query Node:**
   ```json
   {
     "prompt": "Complex analysis task",
     "profile_id": "profile-1764006444002-z0hdduce9"
   }
   ```

3. **Dynamic Profile Selection:**
   - Add **Code** node before Submit Query
   - Select profile based on query content
   - See API_REFERENCE.md Section 4.2 for examples

---

### 6.3. Multi-Turn Conversations

**Use Case:** Follow-up questions that reference previous context.

**Implementation:**

1. **Store Session ID:**
   ```javascript
   // In Code node after Create Session
   const staticData = this.getWorkflowStaticData('global');
   staticData.current_session = $json.session_id;
   ```

2. **Reuse Session:**
   ```javascript
   // In next workflow execution
   const sessionId = this.getWorkflowStaticData('global').current_session;
   // Skip "Create Session" if sessionId exists
   ```

3. **Handle Session Expiry:**
   ```javascript
   // If Submit Query returns 404
   if (response.status === 404) {
     // Session expired, create new one
   }
   ```

---

### 6.4. Add Email Notifications

**Use Case:** Send query results via email.

**Implementation:**

1. After **Extract Answer** node, add **Email** node
2. Configuration:
   ```
   To: analyst@company.com
   Subject: Uderia Query Result
   Body (HTML):
     <h2>Query Result</h2>
     <p>{{$json.final_answer}}</p>
     <hr>
     <p><strong>Tokens Used:</strong> {{$json.total_tokens}}</p>
     <p><strong>Profile:</strong> {{$json.profile_tag}}</p>
   ```

---

### 6.5. Schedule Workflows

**Use Case:** Daily/hourly reports.

**Implementation:**

1. Replace **Manual Trigger** with **Cron** node
2. Configuration:
   ```
   Mode: Every Day
   Hour: 8
   Minute: 0
   ```

3. Example: Daily inventory report at 8 AM
   - See: **WORKFLOW_TEMPLATES.md** → Scheduled Daily Report

---

### 6.6. Integrate with External Services

**Options:**
- **Slack:** Post results to channel (webhook trigger + response)
- **Database:** Store results in PostgreSQL/MySQL
- **Google Sheets:** Append query results to spreadsheet
- **Jira:** Create ticket with analysis findings

**See:** WORKFLOW_TEMPLATES.md for Slack integration example

---

### 6.7. Monitor Cost and Usage

**Track Token Usage:**

```javascript
// In Code node after Extract Answer
const staticData = this.getWorkflowStaticData('global');
const usage = staticData.usage_tracking || {total_tokens: 0, total_queries: 0};

usage.total_tokens += $json.total_tokens;
usage.total_queries += 1;

staticData.usage_tracking = usage;

return {
  json: {
    ...$json,
    cumulative_tokens: usage.total_tokens,
    cumulative_queries: usage.total_queries,
    avg_tokens_per_query: (usage.total_tokens / usage.total_queries).toFixed(0)
  }
};
```

**Cost Calculation:**
- See: **API_REFERENCE.md** Section 6.3
- Use token counts × provider pricing
- Example: Claude Sonnet 4 → $0.003/1K input, $0.015/1K output

---

### 6.8. Learn More

**Documentation:**
- **[API_REFERENCE.md](API_REFERENCE.md)** - Complete endpoint reference
- **[WORKFLOW_TEMPLATES.md](WORKFLOW_TEMPLATES.md)** - Advanced patterns
- **Uderia REST API Docs:** `http://localhost:5050/docs/RestAPI/restAPI.md`

**Community:**
- n8n Community: https://community.n8n.io
- Uderia Issues: https://github.com/anthropics/claude-code/issues

---

## Congratulations! 🎉

You've successfully built your first Uderia + n8n integration. You now know how to:

✅ Authenticate with access tokens
✅ Create sessions
✅ Submit queries
✅ Poll for results
✅ Extract answers and token counts
✅ Handle errors and timeouts

**Next:** Explore [WORKFLOW_TEMPLATES.md](WORKFLOW_TEMPLATES.md) for production-ready workflows!
