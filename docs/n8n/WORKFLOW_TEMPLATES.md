# Uderia + n8n: Reference Workflow Templates

**Purpose:** Three battle-tested n8n workflows ready to import and customize.

**Included Workflows:**
1. **Simple Query** - Manual trigger for interactive testing
2. **Scheduled Daily Report** - Cron-based automation
3. **Slack Integration** - Webhook-driven query execution

---

## Table of Contents

1. [Overview](#overview)
2. [Import Instructions](#import-instructions)
3. [Workflow 1: Simple Query](#workflow-1-simple-query-manual-trigger)
4. [Workflow 2: Scheduled Daily Report](#workflow-2-scheduled-daily-report)
5. [Workflow 3: Slack Integration](#workflow-3-slack-integration)
6. [Advanced Patterns](#advanced-patterns)

---

## Overview

### What Are These Workflows?

These are **production-ready n8n workflows** that demonstrate:
- Complete Uderia REST API integration
- Proper error handling
- Token usage tracking
- Profile override mechanisms
- Real-world use cases

### Who Should Use These?

- **n8n beginners:** Learn by example
- **Integration developers:** Copy-paste starting points
- **DevOps teams:** Production automation templates

### Before You Begin

Ensure you have:
1. ✅ Uderia running and accessible
2. ✅ n8n installed (cloud, self-hosted, or desktop)
3. ✅ Access token created (see [QUICKSTART.md](QUICKSTART.md))
4. ✅ n8n credential configured ("Uderia API Token")
5. ✅ Default profile set in Uderia

---

## Import Instructions

### Method 1: Manual Import (Recommended)

1. **Copy Workflow JSON**
   - Scroll to workflow section below
   - Find "n8n JSON Export" subsection
   - Copy entire JSON block

2. **Import to n8n**
   - Open n8n web interface
   - Click: **"+ New workflow"**
   - Click: **"⋮" menu (top right) → "Import from File"**
   - Paste JSON
   - Click: **"Import"**

3. **Configure Credentials**
   - Open any HTTP Request node
   - Authentication → Select Credential → **"Uderia API Token"**
   - If credential doesn't exist, create it (see QUICKSTART.md Section 2.2)

4. **Update Base URL**
   - If Uderia is not on `localhost:5050`
   - Update all HTTP Request node URLs
   - Example: Replace `http://localhost:5050` with `http://uderia.company.com:5050`

---

### Method 2: Import from File

1. **Download Workflow File**
   - See `docs/n8n/workflows/` directory
   - Download `.json` file

2. **Import to n8n**
   - n8n → **"+ New workflow"**
   - **"⋮" menu → "Import from File"**
   - Select downloaded `.json` file
   - Click: **"Open"**

3. **Configure as above**

---

### Configuration Checklist

Before executing any imported workflow:

- [ ] **Credentials configured** - "Uderia API Token" with valid access token
- [ ] **Base URL updated** - If Uderia is not on localhost
- [ ] **Default profile set** - In Uderia UI (Setup → Profiles)
- [ ] **Workflow activated** - For scheduled/webhook workflows (switch at top)
- [ ] **Test query customized** - Change prompt to your use case

---

## Workflow 1: Simple Query (Manual Trigger)

### Use Case

**Interactive testing and ad-hoc queries.** User manually triggers workflow, enters a question, and receives formatted answer.

**Best For:**
- Testing Uderia connectivity
- Validating profile configuration
- Exploring different query types
- Debugging API responses
- Development and prototyping

---

### Architecture Diagram

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────┐
│   Manual    │────▶│   Create    │────▶│   Submit    │────▶│   Poll   │
│   Trigger   │     │   Session   │     │    Query    │     │   Loop   │
└─────────────┘     └─────────────┘     └─────────────┘     └────┬─────┘
                                                                   │
                    ┌─────────────┐     ┌─────────────┐          │
                    │   Display   │◀────│   Extract   │◀─────────┘
                    │   Answer    │     │    Result   │
                    └─────────────┘     └─────────────┘
```

### Key Features

✅ **Profile-agnostic extraction** - Works with all Uderia profile types
✅ **Robust error handling** - Success/error/timeout paths
✅ **Token count tracking** - Display input/output tokens
✅ **Timeout detection** - 60-second max wait
✅ **Reusable credential** - Single token for all requests

---

### Node Breakdown

#### 1. Manual Trigger
**Type:** Manual Trigger
**Purpose:** Start workflow on demand

**Configuration:** None required

---

#### 2. Create Session
**Type:** HTTP Request
**Purpose:** Create isolated conversation context

**Configuration:**
```
Method: POST
URL: http://localhost:5050/api/v1/sessions
Authentication: Uderia API Token
Response Format: JSON
```

**Output:**
```json
{
  "session_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef"
}
```

---

#### 3. Store Session Context
**Type:** Set
**Purpose:** Save session ID for subsequent nodes

**Configuration:**
```
Values to Set:
  session_id: {{$json.session_id}}
  created_at: {{$now}}
```

---

#### 4. Submit Query
**Type:** HTTP Request
**Purpose:** Submit natural language query to session

**Configuration:**
```
Method: POST
URL: http://localhost:5050/api/v1/sessions/{{$('Store Session Context').item.json.session_id}}/query
Authentication: Uderia API Token
Body Content Type: JSON

Body:
{
  "prompt": "Show me all databases available on the system"
}
```

**Customization Point:**
Change `"prompt"` to your query. Examples:
- `"List all users in the database"`
- `"Generate a sales report for Q4 2025"`
- `"Explain the schema of the orders table"`

**Output:**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status_url": "/api/v1/tasks/task-9876-5432-1098-7654"
}
```

---

#### 5. Initialize Poll State
**Type:** Set
**Purpose:** Set up polling loop variables

**Configuration:**
```
Values to Set:
  task_id: {{$json.task_id}}
  status: pending
  poll_count: 0
  max_polls: 30
  result: null
```

**Tuning:**
- Increase `max_polls` to 60 for complex queries (120-second timeout)

---

#### 6-9. Poll Loop
**Purpose:** Poll task status every 2 seconds until completion

**Loop Structure:**
```
6. Loop Over Items (condition: status !== complete/error AND poll_count < 30)
   ├─ 7. Wait 2 Seconds
   ├─ 8. Poll Task Status (HTTP Request GET /api/v1/tasks/{task_id})
   └─ 9. Update Poll State (Set: status, poll_count++, result)
```

**Exit Condition:**
- `status === "complete"` → Success
- `status === "error"` → Error
- `poll_count >= 30` → Timeout

---

#### 10. Route by Status
**Type:** Switch
**Purpose:** Route to success/error/timeout handlers

**Rules:**
```
Rule 1: status equals "complete" → Output 0 (Success)
Rule 2: status equals "error" → Output 1 (Error)
Otherwise → Output 2 (Timeout)
```

---

#### 11. Extract Answer (Success Path)
**Type:** Code
**Purpose:** Parse profile-agnostic common fields

**Code:**
```javascript
const taskData = $input.item.json;
const result = taskData.result;

if (!result) {
  return {
    json: {
      error: true,
      message: "No result found",
      status: taskData.status
    }
  };
}

const finalAnswer = result.final_answer_text || result.final_answer || "No answer provided";

return {
  json: {
    final_answer: finalAnswer,
    profile_tag: result.profile_tag || "unknown",
    profile_type: result.profile_type || "unknown",
    input_tokens: result.turn_input_tokens || 0,
    output_tokens: result.turn_output_tokens || 0,
    total_tokens: (result.turn_input_tokens || 0) + (result.turn_output_tokens || 0),
    turn_id: result.turn_id,
    poll_count: taskData.poll_count
  }
};
```

**Output Example:**
```json
{
  "final_answer": "There are 3 databases: DEMO_DB, ANALYTICS_DB, REPORTING_DB",
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

#### 12. Handle Error (Error Path)
**Type:** Stop and Error
**Purpose:** Display error message

**Configuration:**
```
Error Message:
  Query failed: {{$('Update Poll State').item.json.result.error || 'Unknown error'}}
```

---

#### 13. Handle Timeout (Timeout Path)
**Type:** Stop and Error
**Purpose:** Display timeout message

**Configuration:**
```
Error Message:
  Query timed out after {{$('Update Poll State').item.json.poll_count}} polls
```

---

### Testing Steps

#### Test 1: Simple Query Success

1. **Execute Workflow**
   - Click: **"Execute Workflow"**

2. **Expected Behavior**
   - All nodes turn green
   - Poll Loop iterates 5-15 times
   - Extract Answer shows database names
   - Tokens are non-zero

3. **Verify Output**
   ```json
   {
     "final_answer": "There are 3 databases: ...",
     "input_tokens": 4523,
     "output_tokens": 287,
     "poll_count": 5
   }
   ```

---

#### Test 2: Complex Query

1. **Edit Submit Query Node**
   ```json
   {
     "prompt": "Generate a detailed report of all products with inventory below 10 units, including supplier information and last order date"
   }
   ```

2. **Execute Workflow**

3. **Expected Behavior**
   - Poll count higher (10-20)
   - More tokens consumed
   - Longer execution time

---

#### Test 3: Error Handling

1. **Temporarily Revoke Token**
   - Uderia UI → Administration → Access Tokens → Revoke

2. **Execute Workflow**

3. **Expected Behavior**
   - Create Session node fails with 401
   - Workflow stops with error

4. **Fix:** Regenerate token and update credential

---

#### Test 4: Timeout Handling

1. **Edit Initialize Poll State**
   ```
   max_polls: 3  (force timeout)
   ```

2. **Execute Workflow**

3. **Expected Behavior**
   - Poll Loop runs 3 times
   - Timeout path triggered
   - Error message: "Query timed out after 3 polls"

4. **Revert:** Change `max_polls` back to 30

---

### Expected Output

**Successful Execution:**
```
Execution Order:
  1. Manual Trigger → 0.1s
  2. Create Session → 0.3s
  3. Store Session Context → 0.1s
  4. Submit Query → 0.5s
  5. Initialize Poll State → 0.1s
  6-9. Poll Loop (5 iterations) → 10s
  10. Route by Status → 0.1s
  11. Extract Answer → 0.2s

Total: ~11 seconds
```

**Output Data:**
```json
{
  "final_answer": "The system has 3 databases available:\n\n1. **DEMO_DB** - Demonstration database for testing\n2. **ANALYTICS_DB** - Data warehouse for analytics queries\n3. **REPORTING_DB** - Reporting system with aggregated data\n\nYou can query any of these databases using the appropriate MCP server connection.",
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

### Customization Options

#### 1. Change Query Prompt

**Location:** Submit Query node → Body

**Examples:**
```json
// Simple queries
{"prompt": "List all tables in DEMO_DB"}
{"prompt": "Count total users"}
{"prompt": "Show recent orders"}

// Complex queries
{"prompt": "Generate a sales report for Q4 2025 with year-over-year comparison"}
{"prompt": "Analyze customer churn patterns in the last 6 months"}
```

---

#### 2. Profile Override

**Location:** Submit Query node → Body

```json
{
  "prompt": "Your query here",
  "profile_id": "profile-1764006444002-z0hdduce9"
}
```

**Use Cases:**
- Switch to GPT-4 for complex reasoning
- Use RAG profile for knowledge retrieval
- Use lightweight profile for fast responses

**Get Profile IDs:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/v1/profiles | jq '.[] | {id, tag}'
```

---

#### 3. Dynamic Prompt from Input

**Add Input Node before Submit Query:**

**Input Node:**
```
Type: Manual Input
Fields:
  - user_question (string)
```

**Submit Query Body:**
```json
{
  "prompt": "{{$('Manual Input').item.json.user_question}}"
}
```

---

#### 4. Add Email Output

**After Extract Answer, add Email node:**

```
To: analyst@company.com
Subject: Uderia Query Result
Body (HTML):
  <h2>Query Result</h2>
  <p>{{$json.final_answer}}</p>
  <hr>
  <p><strong>Tokens Used:</strong> {{$json.total_tokens}}</p>
  <p><strong>Profile:</strong> {{$json.profile_tag}}</p>
  <p><strong>Completed in:</strong> {{$json.poll_count}} polls</p>
```

---

### n8n JSON Export

```json
{
  "name": "Uderia Simple Query",
  "nodes": [
    {
      "parameters": {},
      "name": "Manual Trigger",
      "type": "n8n-nodes-base.manualTrigger",
      "typeVersion": 1,
      "position": [250, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "http://localhost:5050/api/v1/sessions",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "headerAuth",
        "options": {
          "response": {
            "response": {
              "responseFormat": "json"
            }
          }
        }
      },
      "name": "Create Session",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.1,
      "position": [450, 300],
      "credentials": {
        "headerAuth": {
          "id": "CREDENTIAL_ID_PLACEHOLDER",
          "name": "Uderia API Token"
        }
      }
    },
    {
      "parameters": {
        "mode": "manual",
        "duplicateItem": false,
        "assignments": {
          "assignments": [
            {
              "id": "session_id",
              "name": "session_id",
              "type": "string",
              "value": "={{$json.session_id}}"
            },
            {
              "id": "created_at",
              "name": "created_at",
              "type": "string",
              "value": "={{$now}}"
            }
          ]
        }
      },
      "name": "Store Session Context",
      "type": "n8n-nodes-base.set",
      "typeVersion": 3.2,
      "position": [650, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "=http://localhost:5050/api/v1/sessions/{{$('Store Session Context').item.json.session_id}}/query",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "headerAuth",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={\n  \"prompt\": \"Show me all databases available on the system\"\n}",
        "options": {
          "response": {
            "response": {
              "responseFormat": "json"
            }
          }
        }
      },
      "name": "Submit Query",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.1,
      "position": [850, 300],
      "credentials": {
        "headerAuth": {
          "id": "CREDENTIAL_ID_PLACEHOLDER",
          "name": "Uderia API Token"
        }
      }
    },
    {
      "parameters": {
        "mode": "manual",
        "duplicateItem": false,
        "assignments": {
          "assignments": [
            {
              "id": "task_id",
              "name": "task_id",
              "type": "string",
              "value": "={{$json.task_id}}"
            },
            {
              "id": "status",
              "name": "status",
              "type": "string",
              "value": "pending"
            },
            {
              "id": "poll_count",
              "name": "poll_count",
              "type": "number",
              "value": "0"
            },
            {
              "id": "max_polls",
              "name": "max_polls",
              "type": "number",
              "value": "30"
            },
            {
              "id": "result",
              "name": "result",
              "type": "string",
              "value": "null"
            }
          ]
        }
      },
      "name": "Initialize Poll State",
      "type": "n8n-nodes-base.set",
      "typeVersion": 3.2,
      "position": [1050, 300]
    },
    {
      "parameters": {
        "options": {}
      },
      "name": "Poll Loop",
      "type": "n8n-nodes-base.splitInBatches",
      "typeVersion": 3,
      "position": [1250, 300]
    },
    {
      "parameters": {
        "amount": 2,
        "unit": "seconds"
      },
      "name": "Wait 2 Seconds",
      "type": "n8n-nodes-base.wait",
      "typeVersion": 1,
      "position": [1450, 300],
      "webhookId": "auto-generated-webhook-id"
    },
    {
      "parameters": {
        "method": "GET",
        "url": "=http://localhost:5050/api/v1/tasks/{{$('Initialize Poll State').item.json.task_id}}",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "headerAuth",
        "options": {
          "response": {
            "response": {
              "responseFormat": "json"
            }
          }
        }
      },
      "name": "Poll Task Status",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.1,
      "position": [1650, 300],
      "credentials": {
        "headerAuth": {
          "id": "CREDENTIAL_ID_PLACEHOLDER",
          "name": "Uderia API Token"
        }
      }
    },
    {
      "parameters": {
        "mode": "manual",
        "duplicateItem": false,
        "assignments": {
          "assignments": [
            {
              "id": "task_id",
              "name": "task_id",
              "type": "string",
              "value": "={{$('Initialize Poll State').item.json.task_id}}"
            },
            {
              "id": "status",
              "name": "status",
              "type": "string",
              "value": "={{$json.status}}"
            },
            {
              "id": "poll_count",
              "name": "poll_count",
              "type": "number",
              "value": "={{$('Initialize Poll State').item.json.poll_count + 1}}"
            },
            {
              "id": "max_polls",
              "name": "max_polls",
              "type": "number",
              "value": "={{$('Initialize Poll State').item.json.max_polls}}"
            },
            {
              "id": "result",
              "name": "result",
              "type": "object",
              "value": "={{$json.result}}"
            }
          ]
        }
      },
      "name": "Update Poll State",
      "type": "n8n-nodes-base.set",
      "typeVersion": 3.2,
      "position": [1850, 300]
    },
    {
      "parameters": {
        "rules": {
          "rules": [
            {
              "operation": "equal",
              "value1": "={{$('Update Poll State').item.json.status}}",
              "value2": "complete",
              "output": 0
            },
            {
              "operation": "equal",
              "value1": "={{$('Update Poll State').item.json.status}}",
              "value2": "error",
              "output": 1
            }
          ]
        },
        "fallbackOutput": 2
      },
      "name": "Route by Status",
      "type": "n8n-nodes-base.switch",
      "typeVersion": 2,
      "position": [2050, 300]
    },
    {
      "parameters": {
        "jsCode": "const taskData = $input.item.json;\nconst result = taskData.result;\n\nif (!result) {\n  return {\n    json: {\n      error: true,\n      message: \"No result found\",\n      status: taskData.status\n    }\n  };\n}\n\nconst finalAnswer = result.final_answer_text || result.final_answer || \"No answer provided\";\n\nreturn {\n  json: {\n    final_answer: finalAnswer,\n    profile_tag: result.profile_tag || \"unknown\",\n    profile_type: result.profile_type || \"unknown\",\n    input_tokens: result.turn_input_tokens || 0,\n    output_tokens: result.turn_output_tokens || 0,\n    total_tokens: (result.turn_input_tokens || 0) + (result.turn_output_tokens || 0),\n    turn_id: result.turn_id,\n    poll_count: taskData.poll_count\n  }\n};"
      },
      "name": "Extract Answer",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [2250, 200]
    },
    {
      "parameters": {
        "errorMessage": "=Query failed: {{$('Update Poll State').item.json.result.error || 'Unknown error'}}"
      },
      "name": "Handle Error",
      "type": "n8n-nodes-base.stopAndError",
      "typeVersion": 1,
      "position": [2250, 300]
    },
    {
      "parameters": {
        "errorMessage": "=Query timed out after {{$('Update Poll State').item.json.poll_count}} polls ({{$('Update Poll State').item.json.poll_count * 2}} seconds)"
      },
      "name": "Handle Timeout",
      "type": "n8n-nodes-base.stopAndError",
      "typeVersion": 1,
      "position": [2250, 400]
    }
  ],
  "connections": {
    "Manual Trigger": {
      "main": [[{"node": "Create Session", "type": "main", "index": 0}]]
    },
    "Create Session": {
      "main": [[{"node": "Store Session Context", "type": "main", "index": 0}]]
    },
    "Store Session Context": {
      "main": [[{"node": "Submit Query", "type": "main", "index": 0}]]
    },
    "Submit Query": {
      "main": [[{"node": "Initialize Poll State", "type": "main", "index": 0}]]
    },
    "Initialize Poll State": {
      "main": [[{"node": "Poll Loop", "type": "main", "index": 0}]]
    },
    "Poll Loop": {
      "main": [[{"node": "Wait 2 Seconds", "type": "main", "index": 0}], [{"node": "Route by Status", "type": "main", "index": 0}]]
    },
    "Wait 2 Seconds": {
      "main": [[{"node": "Poll Task Status", "type": "main", "index": 0}]]
    },
    "Poll Task Status": {
      "main": [[{"node": "Update Poll State", "type": "main", "index": 0}]]
    },
    "Update Poll State": {
      "main": [[{"node": "Poll Loop", "type": "main", "index": 0}]]
    },
    "Route by Status": {
      "main": [
        [{"node": "Extract Answer", "type": "main", "index": 0}],
        [{"node": "Handle Error", "type": "main", "index": 0}],
        [{"node": "Handle Timeout", "type": "main", "index": 0}]
      ]
    }
  },
  "pinData": {},
  "settings": {
    "executionOrder": "v1"
  },
  "staticData": null,
  "tags": ["uderia", "query", "manual"],
  "triggerCount": 0,
  "updatedAt": "2026-02-09T18:00:00.000Z",
  "versionId": "1"
}
```

**Note:** Replace `CREDENTIAL_ID_PLACEHOLDER` with your n8n credential ID after import.

---

## Workflow 2: Scheduled Daily Report

### Use Case

**Automated daily/weekly/monthly reports delivered to stakeholders.** Runs on a schedule (cron trigger), queries Uderia for analytics, and emails formatted results.

**Best For:**
- Daily inventory reports
- Weekly sales summaries
- Monthly performance dashboards
- Automated data exports
- Regular health checks

---

### Architecture Diagram

```
┌──────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────┐
│  Cron    │────▶│   Create    │────▶│   Submit    │────▶│   Poll   │
│ Trigger  │     │   Session   │     │    Query    │     │   Loop   │
│(Daily 8AM)│     │(@FOCUS)     │     │  (Report)   │     │          │
└──────────┘     └─────────────┘     └─────────────┘     └────┬─────┘
                                                               │
                 ┌─────────────┐     ┌─────────────┐         │
                 │   Email     │◀────│   Format    │◀────────┘
                 │   Report    │     │  as HTML    │
                 └─────────────┘     └─────────────┘
```

### Key Features

✅ **Scheduled execution** - Daily at 8 AM (customizable)
✅ **Profile override** - Uses @FOCUS profile for reporting
✅ **Cost tracking** - Logs token usage for monitoring
✅ **Email distribution** - HTML-formatted reports
✅ **Error notifications** - Alerts on failure

---

### Node Breakdown

#### 1. Cron Trigger
**Type:** Cron
**Purpose:** Trigger workflow daily at 8 AM

**Configuration:**
```
Mode: Every Day
Hour: 8
Minute: 0
Timezone: America/New_York (adjust to your timezone)
```

**Customization:**
- **Weekly:** Mode → Every Week, Day of Week → Monday
- **Hourly:** Mode → Every Hour
- **Custom:** Mode → Custom, Expression → `0 8 * * *` (cron syntax)

---

#### 2-5. Session & Query (Same as Workflow 1)

**Nodes:**
- Create Session (HTTP Request)
- Store Session Context (Set)
- Submit Query (HTTP Request)
- Initialize Poll State (Set)

**Key Difference:** Submit Query uses report-specific prompt and profile override.

---

#### 4. Submit Query (Modified for Reports)
**Type:** HTTP Request

**Body:**
```json
{
  "prompt": "Generate a comprehensive daily inventory report showing:\n1. Products with inventory below 10 units (critical)\n2. Products with inventory below 50 units (warning)\n3. Top 10 products by inventory value\n4. Products with no movement in the last 7 days\n\nInclude supplier information and last restocking date for critical items.",
  "profile_id": "profile-focus-1234567890"
}
```

**Profile Override:**
- Use `@FOCUS` profile (optimized for reporting)
- Get profile ID: `GET /api/v1/profiles | jq '.[] | select(.tag == "@FOCUS") | .id'`

---

#### 6-10. Poll Loop (Same as Workflow 1)

**No changes** from Workflow 1 poll loop structure.

---

#### 11. Extract and Format Report
**Type:** Code
**Purpose:** Format result as HTML email

**Code:**
```javascript
const taskData = $input.item.json;
const result = taskData.result;

if (!result) {
  return {
    json: {
      error: true,
      message: "Report generation failed"
    }
  };
}

const finalAnswer = result.final_answer_text || result.final_answer;

// Format as HTML
const htmlReport = `
<!DOCTYPE html>
<html>
<head>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
    h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
    h2 { color: #34495e; margin-top: 30px; }
    .metadata { background: #ecf0f1; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
    .metadata p { margin: 5px 0; }
    .content { line-height: 1.6; }
    .footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #bdc3c7; font-size: 12px; color: #7f8c8d; }
  </style>
</head>
<body>
  <h1>Daily Inventory Report</h1>

  <div class="metadata">
    <p><strong>Generated:</strong> ${new Date().toLocaleString()}</p>
    <p><strong>Profile:</strong> ${result.profile_tag}</p>
    <p><strong>Tokens Used:</strong> ${result.turn_input_tokens + result.turn_output_tokens} (${result.turn_input_tokens} in / ${result.turn_output_tokens} out)</p>
    <p><strong>Execution Time:</strong> ${taskData.poll_count * 2} seconds</p>
  </div>

  <div class="content">
    ${finalAnswer.replace(/\n/g, '<br>')}
  </div>

  <div class="footer">
    <p>This report was automatically generated by Uderia Platform via n8n.</p>
    <p>Questions? Contact: analytics@company.com</p>
  </div>
</body>
</html>
`;

return {
  json: {
    html_report: htmlReport,
    plain_text: finalAnswer,
    profile: result.profile_tag,
    input_tokens: result.turn_input_tokens,
    output_tokens: result.turn_output_tokens,
    total_tokens: result.turn_input_tokens + result.turn_output_tokens,
    execution_time_seconds: taskData.poll_count * 2,
    generated_at: new Date().toISOString()
  }
};
```

---

#### 12. Email Report
**Type:** Email Send
**Purpose:** Send formatted report to stakeholders

**Configuration:**
```
To: inventory-team@company.com,management@company.com
Subject: Daily Inventory Report - {{$now.format('YYYY-MM-DD')}}
Body (HTML): {{$json.html_report}}

Attachments: None (or add CSV/PDF generation)
```

**Customization:**
- Add BCC for archive
- Attach generated PDF (use PDF generation node)
- Conditional recipients based on report content

---

#### 13. Track Usage (Optional)
**Type:** Code
**Purpose:** Log token usage for cost monitoring

**Code:**
```javascript
// Store cumulative usage in workflow static data
const staticData = this.getWorkflowStaticData('global');
const usage = staticData.usage_tracking || {
  total_tokens: 0,
  total_queries: 0,
  total_cost_usd: 0,
  last_reset: new Date().toISOString()
};

const inputTokens = $json.input_tokens;
const outputTokens = $json.output_tokens;

// Calculate cost (example: Claude Sonnet 4 pricing)
const inputCostPer1k = 0.003;
const outputCostPer1k = 0.015;
const cost = (inputTokens / 1000 * inputCostPer1k) + (outputTokens / 1000 * outputCostPer1k);

usage.total_tokens += inputTokens + outputTokens;
usage.total_queries += 1;
usage.total_cost_usd += cost;

staticData.usage_tracking = usage;

return {
  json: {
    current_query_cost_usd: cost.toFixed(4),
    cumulative_tokens: usage.total_tokens,
    cumulative_queries: usage.total_queries,
    cumulative_cost_usd: usage.total_cost_usd.toFixed(2),
    avg_tokens_per_query: (usage.total_tokens / usage.total_queries).toFixed(0)
  }
};
```

---

#### 14. Error Notification (Error Path)
**Type:** Email Send
**Purpose:** Alert team if report generation fails

**Configuration:**
```
To: devops@company.com
Subject: 🚨 ALERT: Uderia Daily Report Failed
Body (Plain Text):
The scheduled daily inventory report failed to generate.

Error: {{$('Update Poll State').item.json.result.error}}

Time: {{$now}}
Workflow: Uderia Scheduled Daily Report

Action Required: Check Uderia server logs and MCP server status.
```

---

### Testing Steps

#### Test 1: Manual Trigger Test

1. **Temporarily Change Trigger**
   - Disable Cron node
   - Add Manual Trigger before Create Session

2. **Execute Workflow**

3. **Verify:**
   - Email received with HTML report
   - Token counts logged
   - Execution completes in <30 seconds

4. **Revert:** Remove Manual Trigger, enable Cron

---

#### Test 2: Scheduled Execution

1. **Activate Workflow**
   - Toggle switch at top: **"Inactive" → "Active"**

2. **Set Near-Term Schedule**
   - Cron node → Next 5 minutes
   - Example: If current time is 10:42, set to 10:45

3. **Wait for Execution**

4. **Verify:**
   - n8n Executions list shows automated run
   - Email received at scheduled time

---

#### Test 3: Cost Tracking

1. **Execute Multiple Times**
   - Run manually 3-5 times

2. **Check Usage Tracking**
   - Inspect Track Usage node output
   - Verify cumulative values incrementing

---

### Expected Output

**Email Content (HTML):**
```html
<!DOCTYPE html>
<html>
<body>
  <h1>Daily Inventory Report</h1>

  <div class="metadata">
    <p><strong>Generated:</strong> 2026-02-09 08:00:15</p>
    <p><strong>Profile:</strong> @FOCUS</p>
    <p><strong>Tokens Used:</strong> 6842 (5230 in / 1612 out)</p>
    <p><strong>Execution Time:</strong> 14 seconds</p>
  </div>

  <div class="content">
    <h2>1. Critical Inventory (Below 10 Units)</h2>
    <ul>
      <li><strong>Widget Pro</strong> - 3 units - Supplier: Acme Corp - Last Restocked: 2026-01-15</li>
      <li><strong>Gadget Max</strong> - 7 units - Supplier: Global Supply - Last Restocked: 2026-01-20</li>
    </ul>

    <h2>2. Warning Inventory (Below 50 Units)</h2>
    ...
  </div>
</body>
</html>
```

**Usage Tracking Output:**
```json
{
  "current_query_cost_usd": "0.0398",
  "cumulative_tokens": 34210,
  "cumulative_queries": 5,
  "cumulative_cost_usd": "0.20",
  "avg_tokens_per_query": "6842"
}
```

---

### Customization Options

#### 1. Change Schedule

**Weekly on Monday at 9 AM:**
```
Cron node:
  Mode: Every Week
  Day of Week: Monday
  Hour: 9
  Minute: 0
```

**Last Day of Month:**
```
Mode: Custom
Expression: 0 8 28-31 * *
(Runs on days 28-31, effectively catching month-end)
```

---

#### 2. Multiple Report Types

**Add Switch node after Extract Report:**

```
Switch on: {{$json.report_type}}

Rules:
  - inventory → Email to inventory-team@company.com
  - sales → Email to sales@company.com
  - finance → Email to finance@company.com + CFO
```

**Set report_type in Submit Query:**
```json
{
  "prompt": "Generate inventory report...",
  "report_type": "inventory"
}
```

---

#### 3. Conditional Recipients

**Add If node before Email:**

```
Condition: {{$json.critical_items_count}} > 10

True → Email to: inventory-team@company.com, management@company.com
False → Email to: inventory-team@company.com
```

---

#### 4. Attach PDF

**Add PDF generation:**

1. Install: **"HTML to PDF"** community node
2. After Format Report, add PDF node
3. Email node → Attachments → Add PDF

---

### n8n JSON Export

*[Omitted for brevity - similar structure to Workflow 1 with Cron trigger, modified prompt, email nodes, and usage tracking]*

---

## Workflow 3: Slack Integration

### Use Case

**Slack-driven Uderia queries via slash command.** Users type `/uderia <question>` in Slack, n8n receives webhook, queries Uderia, and posts formatted response back to Slack channel.

**Best For:**
- Team self-service analytics
- Instant data queries from Slack
- Conversational data access
- ChatOps workflows
- On-demand reports

---

### Architecture Diagram

```
┌──────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────┐
│  Slack   │────▶│  Parse      │────▶│   Check     │────▶│  Create  │
│ Webhook  │     │  Payload    │     │Token Cache  │     │  Session │
└──────────┘     └─────────────┘     └─────────────┘     └────┬─────┘
                                                               │
                 ┌─────────────┐     ┌─────────────┐         │
                 │   Post to   │◀────│   Format    │◀────────┤
                 │    Slack    │     │   Blocks    │     Poll Loop
                 └─────────────┘     └─────────────┘
```

### Key Features

✅ **Webhook-triggered** - Responds to Slack slash commands
✅ **Token caching** - Reuses access token (23-hour expiry)
✅ **Session reuse** - Maintains conversation context
✅ **Slack block formatting** - Rich, interactive responses
✅ **Timeout handling** - User-friendly error messages in Slack
✅ **Private responses** - Only requester sees result (ephemeral)

---

### Prerequisites

#### 1. Create Slack App

1. Go to: https://api.slack.com/apps
2. Click: **"Create New App"** → **"From scratch"**
3. App Name: **"Uderia Assistant"**
4. Workspace: Select your workspace
5. Click: **"Create App"**

---

#### 2. Add Slash Command

1. In app settings, go to: **"Slash Commands"**
2. Click: **"Create New Command"**
3. Configuration:
   ```
   Command: /uderia
   Request URL: https://your-n8n-instance.com/webhook/uderia-slack
   Short Description: Query Uderia Platform
   Usage Hint: <your question>
   ```
4. Click: **"Save"**

---

#### 3. Install App to Workspace

1. In app settings, go to: **"Install App"**
2. Click: **"Install to Workspace"**
3. Review permissions and click: **"Allow"**
4. Copy: **"Bot User OAuth Token"** (starts with `xoxb-`)

---

#### 4. Get Webhook URL from n8n

1. Create new workflow in n8n
2. Add **Webhook** trigger node
3. Configuration:
   ```
   HTTP Method: POST
   Path: uderia-slack
   Response Mode: Respond to Webhook
   ```
4. Copy **"Production URL"** (e.g., `https://your-n8n.com/webhook/uderia-slack`)
5. Paste into Slack app "Request URL" (step 2.3)

---

### Node Breakdown

#### 1. Webhook Trigger
**Type:** Webhook
**Purpose:** Receive Slack slash command POST

**Configuration:**
```
HTTP Method: POST
Path: uderia-slack
Response Mode: Respond to Webhook
```

**Slack Payload:**
```json
{
  "token": "verification_token",
  "team_id": "T1234567890",
  "user_id": "U1234567890",
  "user_name": "john.doe",
  "command": "/uderia",
  "text": "Show me sales for Q4 2025",
  "channel_id": "C1234567890",
  "channel_name": "analytics",
  "response_url": "https://hooks.slack.com/commands/..."
}
```

---

#### 2. Parse Slack Payload
**Type:** Code
**Purpose:** Extract and validate Slack request

**Code:**
```javascript
const payload = $input.item.json.body || $input.item.json;

// Extract fields
const userQuery = payload.text || "";
const userId = payload.user_id;
const userName = payload.user_name;
const channelId = payload.channel_id;
const responseUrl = payload.response_url;

// Validate
if (!userQuery || userQuery.trim() === "") {
  return {
    json: {
      error: true,
      slack_response: {
        response_type: "ephemeral",
        text: "❌ Please provide a question after /uderia\n\nExample: `/uderia Show me all databases`"
      }
    }
  };
}

return {
  json: {
    user_query: userQuery.trim(),
    user_id: userId,
    user_name: userName,
    channel_id: channelId,
    response_url: responseUrl
  }
};
```

---

#### 3. Immediate Slack Response
**Type:** Respond to Webhook
**Purpose:** Acknowledge command (Slack requires response within 3 seconds)

**Configuration:**
```
Response Body:
{
  "response_type": "ephemeral",
  "text": "⏳ Processing your query: {{$json.user_query}}\n\nThis may take 10-30 seconds..."
}
```

**Why Needed:**
- Slack slash commands timeout after 3 seconds
- Uderia queries take 10-60 seconds
- This response prevents timeout, then we post result via `response_url`

---

#### 4. Check Token Cache
**Type:** Code
**Purpose:** Reuse access token if not expired (23-hour cache)

**Code:**
```javascript
const staticData = this.getWorkflowStaticData('global');
const cachedToken = staticData.uderia_token;
const tokenExpiresAt = staticData.token_expires_at || 0;
const now = Date.now();

// Check if token exists and not expired (with 1-hour buffer)
const hoursUntilExpiry = (tokenExpiresAt - now) / (1000 * 60 * 60);

if (cachedToken && hoursUntilExpiry > 1) {
  // Token still valid
  return {
    json: {
      access_token: cachedToken,
      token_cached: true,
      expires_in_hours: hoursUntilExpiry.toFixed(1)
    }
  };
}

// Token expired or doesn't exist
return {
  json: {
    access_token: null,
    token_cached: false,
    needs_regeneration: true
  }
};
```

---

#### 5. Refresh Token (If Needed)
**Type:** If + HTTP Request
**Purpose:** Generate new token if cache expired

**If Condition:**
```
{{$json.needs_regeneration}} equals true
```

**HTTP Request (inside If):**
```
Method: POST
URL: http://localhost:5050/auth/login
Body:
{
  "username": "slack_bot",
  "password": "secure_password"
}
```

**Then create access token:**
```
Method: POST
URL: http://localhost:5050/api/v1/auth/tokens
Authorization: Bearer {{$json.token}}
Body:
{
  "name": "Slack Integration",
  "expires_in_days": 90
}
```

**Store Token:**
```javascript
// Code node
const staticData = this.getWorkflowStaticData('global');
staticData.uderia_token = $json.token;
staticData.token_expires_at = Date.now() + (90 * 24 * 60 * 60 * 1000);

return {json: {access_token: $json.token}};
```

---

#### 6-10. Query Uderia (Same Pattern)

**Nodes:**
- Create Session
- Submit Query (uses `user_query` from Parse Slack Payload)
- Initialize Poll State
- Poll Loop (6a-6c: Wait, Poll, Update)
- Route by Status

---

#### 11. Format as Slack Blocks
**Type:** Code
**Purpose:** Create rich Slack message with blocks

**Code:**
```javascript
const result = $input.item.json.result;
const finalAnswer = result.final_answer_text || result.final_answer;

// Format Slack blocks
const slackBlocks = {
  response_type: "in_channel",  // or "ephemeral" for private
  blocks: [
    {
      type: "header",
      text: {
        type: "plain_text",
        text: "✅ Uderia Query Result"
      }
    },
    {
      type: "section",
      text: {
        type: "mrkdwn",
        text: finalAnswer
      }
    },
    {
      type: "context",
      elements: [
        {
          type: "mrkdwn",
          text: `*Profile:* ${result.profile_tag} | *Tokens:* ${result.turn_input_tokens + result.turn_output_tokens} | *Time:* ${$('Update Poll State').item.json.poll_count * 2}s`
        }
      ]
    }
  ]
};

return {
  json: {
    slack_message: slackBlocks,
    response_url: $('Parse Slack Payload').item.json.response_url
  }
};
```

---

#### 12. Post to Slack
**Type:** HTTP Request
**Purpose:** Send result to Slack via response_url

**Configuration:**
```
Method: POST
URL: {{$json.response_url}}
Body Content Type: JSON
Body:
  {{$json.slack_message}}
```

**Why response_url:**
- Allows delayed responses (after initial 3-second ack)
- Can post up to 30 minutes after initial command
- Supports ephemeral (private) and in_channel (public) responses

---

#### 13. Handle Errors (Error Path)
**Type:** HTTP Request
**Purpose:** Post error message to Slack

**Code (Format Error):**
```javascript
const error = $('Update Poll State').item.json.result?.error || "Unknown error";

return {
  json: {
    slack_message: {
      response_type: "ephemeral",
      text: `❌ *Query Failed*\n\n${error}\n\nPlease try again or contact support.`
    },
    response_url: $('Parse Slack Payload').item.json.response_url
  }
};
```

**Then:** HTTP Request to post error (same as success path)

---

#### 14. Handle Timeout (Timeout Path)
**Type:** HTTP Request
**Purpose:** Post timeout message to Slack

**Code:**
```javascript
const pollCount = $('Update Poll State').item.json.poll_count;

return {
  json: {
    slack_message: {
      response_type: "ephemeral",
      text: `⏱️ *Query Timed Out*\n\nYour query took longer than ${pollCount * 2} seconds.\n\n*Suggestions:*\n• Simplify your question\n• Try again later\n• Contact analytics team for complex queries`
    },
    response_url: $('Parse Slack Payload').item.json.response_url
  }
};
```

---

### Testing Steps

#### Test 1: Webhook Setup Verification

1. **Test with Slack Request Builder**
   - https://api.slack.com/tools/request-builder
   - Method: POST
   - URL: Your n8n webhook URL
   - Body:
     ```json
     {
       "command": "/uderia",
       "text": "List databases",
       "user_name": "test.user",
       "response_url": "https://example.com/test"
     }
     ```

2. **Verify n8n Execution**
   - Workflow executes
   - Parse Slack Payload extracts `text`

---

#### Test 2: Slack Slash Command

1. **In Slack Channel:**
   ```
   /uderia Show me all databases
   ```

2. **Expected Behavior:**
   - Immediate response: "⏳ Processing your query..."
   - After 10-20 seconds: Rich formatted result
   - Metadata shows tokens and time

---

#### Test 3: Error Handling

1. **Test Invalid Query:**
   ```
   /uderia Query non-existent database INVALID_DB
   ```

2. **Expected:** Error message in Slack with helpful guidance

---

#### Test 4: Token Caching

1. **Execute Command**
2. **Check Workflow Execution**
   - Inspect "Check Token Cache" node
   - Verify `token_cached: true` on subsequent runs
3. **After 23 hours:** Verify new token generated

---

### Expected Output

**Slack Message (Success):**

```
✅ Uderia Query Result

There are 3 databases available on the system:

1. **DEMO_DB** - Demonstration database for testing
2. **ANALYTICS_DB** - Data warehouse for analytics queries
3. **REPORTING_DB** - Reporting system with aggregated data

You can query any of these databases using appropriate MCP connections.

────────────────────────────
Profile: @GOGET | Tokens: 4810 | Time: 14s
```

**Slack Message (Error):**

```
❌ Query Failed

MCP server connection failed: Database 'INVALID_DB' not found

Please try again or contact support.
```

---

### Customization Options

#### 1. Profile Routing by Channel

**Use Case:** Different Slack channels use different Uderia profiles.

**Add Switch node after Parse Slack Payload:**
```
Switch on: {{$json.channel_id}}

Rules:
  - C1234567890 (analytics channel) → profile_id: "profile-focus-123"
  - C0987654321 (sales channel) → profile_id: "profile-sales-456"
  - Otherwise → profile_id: null (use default)
```

---

#### 2. User Authorization

**Add If node after Parse Slack Payload:**
```
Condition: {{$json.user_id}} in ["U123", "U456", "U789"]

False → Respond with: "❌ You don't have permission to use /uderia"
True → Continue to query
```

---

#### 3. Interactive Buttons

**Add buttons to Slack response:**
```javascript
const slackBlocks = {
  response_type: "in_channel",
  blocks: [
    // ... result blocks ...
    {
      type: "actions",
      elements: [
        {
          type: "button",
          text: {type: "plain_text", text: "Email Report"},
          action_id: "email_report"
        },
        {
          type: "button",
          text: {type: "plain_text", text: "Export CSV"},
          action_id: "export_csv"
        }
      ]
    }
  ]
};
```

**Handle button clicks:** Add separate webhook workflow listening for Slack interactivity payloads.

---

#### 4. Multi-Turn Conversations

**Store session ID per Slack user:**

```javascript
const staticData = this.getWorkflowStaticData('global');
const sessions = staticData.user_sessions || {};
const userId = $('Parse Slack Payload').item.json.user_id;

// Get or create session
let sessionId = sessions[userId];
if (!sessionId || isSessionExpired(sessionId)) {
  // Create new session
  sessionId = await createNewSession();
  sessions[userId] = sessionId;
  staticData.user_sessions = sessions;
}

return {json: {session_id: sessionId, reused: !!sessions[userId]}};
```

**Benefit:** Follow-up questions reference previous context.

---

### n8n JSON Export

*[Omitted for brevity - includes Webhook trigger, Slack payload parsing, token caching, query execution, and Slack block formatting]*

---

## Advanced Patterns

### Pattern 1: Batch Query Processing

**Use Case:** Submit multiple queries in parallel, collect all results.

**Implementation:**

1. **Split Queries:**
   ```javascript
   const queries = [
     "Count total users",
     "List all databases",
     "Show recent orders"
   ];

   return queries.map(prompt => ({json: {prompt}}));
   ```

2. **Loop Over Queries:**
   - Use "Loop Over Items" node
   - For each query: Create session → Submit → Poll → Extract

3. **Merge Results:**
   - Use "Merge" node to combine all outputs
   - Format as single report

---

### Pattern 2: Profile Performance A/B Testing

**Use Case:** Compare response quality and cost across different profiles.

**Implementation:**

1. **Duplicate Query Branch:**
   - Submit same query with different `profile_id`
   - Profile A: @GOGET (Claude Sonnet)
   - Profile B: @GEMINI (Gemini Flash)

2. **Collect Metrics:**
   ```javascript
   return {
     json: {
       profile: result.profile_tag,
       tokens: result.turn_input_tokens + result.turn_output_tokens,
       cost: calculateCost(result),
       execution_time_s: pollCount * 2,
       answer_length: result.final_answer.length
     }
   };
   ```

3. **Compare:**
   - Side-by-side analysis
   - Log to database for trend analysis

---

### Pattern 3: Approval Workflow

**Use Case:** Expensive queries require manager approval before execution.

**Implementation:**

1. **Check Query Cost Estimate:**
   ```javascript
   const queryComplexity = estimateComplexity($json.prompt);
   if (queryComplexity > threshold) {
     return {json: {requires_approval: true}};
   }
   ```

2. **Send Approval Request:**
   - Email to manager with approve/reject links
   - Links point to n8n webhook endpoints

3. **Wait for Approval:**
   - Use "Wait" node with webhook resume
   - Timeout after 24 hours

4. **Execute if Approved:**
   - Continue to query execution
   - Or abort and notify requester

---

### Pattern 4: Result Caching

**Use Case:** Cache frequent queries to save costs.

**Implementation:**

1. **Hash Query:**
   ```javascript
   const crypto = require('crypto');
   const queryHash = crypto.createHash('md5').update($json.prompt).digest('hex');
   ```

2. **Check Cache:**
   ```javascript
   const staticData = this.getWorkflowStaticData('global');
   const cache = staticData.query_cache || {};
   const cached = cache[queryHash];

   if (cached && (Date.now() - cached.timestamp < 3600000)) {
     // Cache hit (less than 1 hour old)
     return {json: {result: cached.result, from_cache: true}};
   }
   ```

3. **Store Result:**
   ```javascript
   cache[queryHash] = {
     result: $json.result,
     timestamp: Date.now()
   };
   staticData.query_cache = cache;
   ```

---

### Pattern 5: Progressive Prompting

**Use Case:** Break complex queries into sequential simple queries.

**Implementation:**

1. **Query 1:** "List all databases"
2. **Extract database names from result**
3. **Query 2:** "For each database: {db}, show table count"
4. **Query 3:** "For database with most tables, show schema"

**Loop Through Queries:**
```javascript
const queries = [
  "List all databases",
  $prev_result.databases.map(db => `Show tables in ${db}`),
  "Generate summary report"
].flat();
```

---

## Summary

These three reference workflows provide production-ready starting points for:

1. **Simple Query** - Interactive testing and development
2. **Scheduled Daily Report** - Automated, recurring analytics
3. **Slack Integration** - Team self-service data access

**Next Steps:**
1. Import workflows to your n8n instance
2. Customize queries and prompts for your use cases
3. Configure email recipients, Slack channels, schedules
4. Monitor token usage and costs
5. Extend with advanced patterns as needed

**Support:**
- See [API_REFERENCE.md](API_REFERENCE.md) for endpoint details
- See [QUICKSTART.md](QUICKSTART.md) for basic setup
- Report issues: https://github.com/anthropics/claude-code/issues

---

**End of Workflow Templates Documentation**
