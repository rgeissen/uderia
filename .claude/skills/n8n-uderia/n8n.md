# n8n + Uderia Integration - Complete Development Guide

**Version:** 1.0
**Date:** 2026-02-09
**Purpose:** Comprehensive Claude skill for developing, testing, and deploying n8n workflows with Uderia Platform

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Development Workflow](#development-workflow)
4. [Testing Strategies](#testing-strategies)
5. [Deployment Procedures](#deployment-procedures)
6. [REST API vs UI Differences](#rest-api-vs-ui-differences)
7. [Common Pitfalls & Solutions](#common-pitfalls--solutions)
8. [Docker Networking](#docker-networking)
9. [Reverse Proxy Configuration](#reverse-proxy-configuration)
10. [Reference Examples](#reference-examples)
11. [Troubleshooting Guide](#troubleshooting-guide)

---

## Overview

### What is This Integration?

The n8n + Uderia integration enables **visual workflow automation** for the Uderia AI Platform. Users can:

- Create workflows with visual node-based editor
- Trigger Uderia queries via webhooks, cron schedules, or manual triggers
- Route Uderia responses to external systems (Slack, email, databases)
- Build complex multi-step automations with conditional logic

### Key Components

| Component | Purpose | Location |
|-----------|---------|----------|
| **Uderia Platform** | AI orchestration engine | https://tda.uderia.com (production) or localhost:5050 (local) |
| **n8n** | Workflow automation platform | https://n8n.uderia.com or localhost:5678 |
| **MCP Servers** | Tool providers (database, APIs) | Referenced by Uderia profiles |
| **REST API** | Programmatic Uderia access | `/api/v1/*` endpoints |

### Integration Pattern

```
┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────┐
│   n8n   │─────►│ Uderia  │─────►│   LLM   │      │ MCP │
│ Workflow│ HTTP │REST API │ AI   │Provider │      │ Svr │
└─────────┘      └─────────┘      └─────────┘      └─────┘
                       │                               │
                       └───────────────────────────────┘
                              Tool Execution
```

**Three-Step Pattern:**
1. **Create Session:** `POST /api/v1/sessions` → Returns `session_id`
2. **Submit Query:** `POST /api/v1/sessions/{id}/query` → Returns `task_id`
3. **Poll for Result:** `GET /api/v1/tasks/{id}` → Returns final answer + metadata

---

## Architecture

### Uderia REST API Fundamentals

**Base URLs:**
- **Production:** `https://tda.uderia.com/api/v1`
- **Local Development:** `http://localhost:5050/api/v1`

**Authentication:**
- **Method:** Bearer token authentication
- **Header:** `Authorization: Bearer tda_<token>`
- **Token Types:**
  - JWT (24-hour expiry) - For web UI sessions
  - Access Tokens (90-day or never) - For automation (recommended for n8n)

**Getting an Access Token:**
```bash
# 1. Login to get JWT
JWT=$(curl -s -X POST 'https://tda.uderia.com/api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Amadeu$01"}' | jq -r '.token')

# 2. Create long-lived access token
TOKEN=$(curl -s -X POST 'https://tda.uderia.com/api/v1/auth/tokens' \
  -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' \
  -d '{"name":"n8n Integration","expires_in_days":90}' | jq -r '.token')

echo "Access Token: $TOKEN"
```

### Profile System

**Profiles** combine MCP Server + LLM Provider into reusable configurations.

**Four Profile Types:**

1. **tool_enabled** (Optimizer) - Strategic planning + tool execution
2. **llm_only** (Chat) - Direct LLM conversation
3. **rag_focused** (Knowledge) - Semantic search + synthesis
4. **genie** (Multi-Profile) - Coordinates multiple sub-profiles

**Profile Override Methods:**

| Method | Context | Syntax | Example |
|--------|---------|--------|---------|
| **UI** | Web interface | `@TAG query text` | `@FOCUS Show me databases` |
| **REST API** | n8n workflows | `profile_id` parameter | `{"prompt": "Show me databases", "profile_id": "profile-default-rag"}` |

**CRITICAL:** n8n workflows MUST use the REST API method (`profile_id` parameter), NOT the `@TAG` syntax.

---

## Development Workflow

### Step 1: Environment Setup

**Prerequisites:**
1. Uderia instance running (local or production)
2. n8n instance running (local or production)
3. Access token from Uderia
4. Default profile configured in Uderia

**n8n Credential Configuration:**
```
1. Go to Settings → Credentials
2. Click "+ New Credential"
3. Select "Header Auth"
4. Configure:
   - Name: Uderia API Token
   - Header Name: Authorization
   - Header Value: Bearer tda_<your_token>
5. Save
```

### Step 2: Workflow Design Principles

**Use Ultra-Clean Workflow Pattern:**

n8n has known bugs when importing complex workflows via API:
- **Bug #23620:** API-created workflows fail to render in UI
- **Bug #14775:** Complex parameter structures cause errors

**Solution:** Use simplified linear flows:

✅ **GOOD: Linear Flow (5-7 nodes)**
```
Manual Trigger → Set Config → Prepare Prompt → Create Session →
Submit Query → Wait → Get Result
```

❌ **BAD: Complex Flow (14+ nodes)**
```
Trigger → Create Session → Submit → Loop Start → Wait → Poll →
Switch (pending/complete/error) → If (retry?) → Loop Back →
Extract Result → Format → Email
```

**Key Rules:**
1. **Linear flow** - No loops or complex conditionals
2. **Minimal parameters** - Only specify required fields
3. **Code nodes for logic** - Not inline JavaScript expressions
4. **Import via UI** - Not API (avoids rendering bugs)

### Step 3: Building the Workflow

**Basic Workflow Structure:**

**Node 1: Manual Trigger**
```json
{
  "parameters": {},
  "type": "n8n-nodes-base.manualTrigger",
  "typeVersion": 1,
  "position": [250, 300]
}
```

**Node 2: Set Config** (User-editable parameters)
```json
{
  "parameters": {
    "assignments": {
      "assignments": [
        {
          "name": "profile_id",
          "value": "",
          "type": "string"
        },
        {
          "name": "query",
          "value": "Show me all databases available",
          "type": "string"
        }
      ]
    }
  },
  "type": "n8n-nodes-base.set",
  "typeVersion": 3.2
}
```

**Node 3: Prepare Prompt** (Code node for REST API formatting)
```javascript
const config = $input.first().json;
const profileId = config.profile_id || '';
const query = config.query || '';

const result = {
  prompt: query
};

// Add profile_id only if specified (optional parameter)
if (profileId) {
  result.profile_id = profileId;
}

return { json: result };
```

**Why Code Node?**
- ✅ Reliable for complex logic
- ✅ Handles conditional parameter inclusion
- ✅ Clear, testable JavaScript
- ❌ Inline expressions fail with "invalid syntax" for complex logic

**Node 4: Create Session**
```json
{
  "parameters": {
    "method": "POST",
    "url": "https://tda.uderia.com/api/v1/sessions",
    "authentication": "predefinedCredentialType",
    "nodeCredentialType": "headerAuth",
    "options": {}
  },
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.1
}
```

**Node 5: Submit Query**
```json
{
  "parameters": {
    "method": "POST",
    "url": "=https://tda.uderia.com/api/v1/sessions/{{ $json.session_id }}/query",
    "sendBody": true,
    "specifyBody": "json",
    "jsonBody": "={{ $('Prepare Prompt').item.json }}",
    "authentication": "predefinedCredentialType",
    "nodeCredentialType": "headerAuth"
  },
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.1
}
```

**CRITICAL:** Use `jsonBody: "={{ $('Prepare Prompt').item.json }}"` to reference the prepared data. Do NOT use `JSON.stringify()` or inline expressions.

**Node 6: Wait**
```json
{
  "parameters": {
    "amount": 8,
    "unit": "seconds"
  },
  "type": "n8n-nodes-base.wait",
  "typeVersion": 1
}
```

**Node 7: Get Result**
```json
{
  "parameters": {
    "method": "GET",
    "url": "=https://tda.uderia.com/api/v1/tasks/{{ $json.task_id }}",
    "authentication": "predefinedCredentialType",
    "nodeCredentialType": "headerAuth"
  },
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.1
}
```

### Step 4: Connect Nodes

**connections.json structure:**
```json
{
  "Manual Trigger": {
    "main": [[{"node": "Set Config", "type": "main", "index": 0}]]
  },
  "Set Config": {
    "main": [[{"node": "Prepare Prompt", "type": "main", "index": 0}]]
  },
  "Prepare Prompt": {
    "main": [[{"node": "Create Session", "type": "main", "index": 0}]]
  },
  "Create Session": {
    "main": [[{"node": "Submit Query", "type": "main", "index": 0}]]
  },
  "Submit Query": {
    "main": [[{"node": "Wait", "type": "main", "index": 0}]]
  },
  "Wait": {
    "main": [[{"node": "Get Result", "type": "main", "index": 0}]]
  }
}
```

---

## Testing Strategies

### Local Testing (localhost:5050)

**When to use:**
- Development of new workflows
- Testing profile overrides
- Debugging authentication issues

**Setup:**
```bash
# 1. Start Uderia locally
cd /path/to/uderia
python -m trusted_data_agent.main

# 2. Get access token
JWT=$(curl -s -X POST 'http://localhost:5050/api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | jq -r '.token')

TOKEN=$(curl -s -X POST 'http://localhost:5050/api/v1/auth/tokens' \
  -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Local Testing","expires_in_days":90}' | jq -r '.token')

# 3. Update n8n credential with local token
# 4. Change workflow URLs to http://localhost:5050/api/v1
```

**Testing Checklist:**
- [ ] Session creation succeeds (returns `session_id`)
- [ ] Query submission succeeds (returns `task_id`)
- [ ] Result retrieval returns `status: "complete"`
- [ ] `final_answer` field contains expected content
- [ ] Token counts are non-zero (`turn_input_tokens`, `turn_output_tokens`)
- [ ] Profile override works (check `profile_tag` in result)

### Production Testing (tda.uderia.com)

**When to use:**
- Final validation before deployment
- Testing with production data
- Performance benchmarking

**Setup:**
```bash
# 1. Get production access token (see Architecture section)
# 2. Update n8n credential with production token
# 3. Ensure workflow URLs use https://tda.uderia.com/api/v1
```

**Additional Validation:**
- [ ] Reverse proxy routing works (405 errors resolved)
- [ ] WebSocket connections stable (no "Connection Lost")
- [ ] Credentials encrypted at rest in n8n
- [ ] Rate limiting not triggered

### n8n API Testing (Programmatic)

**When to use:**
- Bulk workflow deployment
- CI/CD integration
- Automated testing

**Import Workflow via API:**
```python
import requests

API_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
BASE_URL = 'https://n8n.uderia.com/api/v1'

with open('simple-query-ultraclean.json', 'r') as f:
    workflow = json.load(f)

response = requests.post(
    f'{BASE_URL}/workflows',
    headers={
        'X-N8N-API-KEY': API_KEY,
        'Content-Type': 'application/json'
    },
    json=workflow
)

workflow_id = response.json()['id']
print(f"Imported: {workflow_id}")
```

**Execute Workflow via API:**
```python
response = requests.post(
    f'{BASE_URL}/workflows/{workflow_id}/execute',
    headers={'X-N8N-API-KEY': API_KEY}
)

execution_id = response.json()['id']
print(f"Executing: {execution_id}")
```

**Check Execution Status:**
```python
response = requests.get(
    f'{BASE_URL}/executions/{execution_id}',
    headers={'X-N8N-API-KEY': API_KEY}
)

status = response.json()['finished']
print(f"Finished: {status}")
```

---

## Deployment Procedures

### Pre-Deployment Checklist

**Workflow Validation:**
- [ ] Workflow imports without errors via UI
- [ ] All nodes execute successfully in test
- [ ] Credentials configured correctly (Uderia API Token)
- [ ] Set Config fields added manually (if using profile override)
- [ ] URLs point to correct environment (production vs local)
- [ ] Wait time sufficient for query completion (8-10 seconds)

**Environment Validation:**
- [ ] Uderia instance accessible from n8n
- [ ] Reverse proxy configured (if using tda.uderia.com)
- [ ] WebSocket headers present (Upgrade, Connection)
- [ ] Docker networking configured (if using containers)
- [ ] Firewall rules allow n8n → Uderia traffic

### Deployment Methods

**Method 1: UI Import (Recommended)**

**Best for:** Manual deployment, small number of workflows

**Steps:**
1. Navigate to n8n UI: https://n8n.uderia.com
2. Click top-right menu (⋮) → "Import from File"
3. Select JSON file (e.g., `simple-query-ultraclean.json`)
4. Click "Import"
5. Workflow opens in editor
6. **Configure Set Config node manually:**
   - Click "Set Config" node
   - Click "Add Field" button
   - Add Field 1: `profile_id` (String, leave empty for default)
   - Add Field 2: `query` (String, e.g., "Show me all databases")
7. **Assign credentials to HTTP Request nodes:**
   - Click each HTTP Request node (Create Session, Submit Query, Get Result)
   - Authentication → Select "Uderia API Token"
8. Click "Save" (top right)
9. Click "Execute Workflow" to test
10. Activate workflow (toggle top-right)

**Method 2: API Import**

**Best for:** CI/CD pipelines, bulk deployments

**Python Script Example:**
```python
#!/usr/bin/env python3
import requests
import json
import sys

API_KEY = 'your_n8n_api_key'
BASE_URL = 'https://n8n.uderia.com/api/v1'

def import_workflow(json_file):
    with open(json_file, 'r') as f:
        workflow = json.load(f)

    response = requests.post(
        f'{BASE_URL}/workflows',
        headers={
            'X-N8N-API-KEY': API_KEY,
            'Content-Type': 'application/json'
        },
        json=workflow
    )

    if response.status_code == 200:
        workflow_id = response.json()['id']
        print(f"✅ Imported: {workflow['name']} (ID: {workflow_id})")
        return workflow_id
    else:
        print(f"❌ Failed: {response.text}")
        return None

def activate_workflow(workflow_id):
    response = requests.patch(
        f'{BASE_URL}/workflows/{workflow_id}',
        headers={'X-N8N-API-KEY': API_KEY},
        json={'active': True}
    )

    if response.status_code == 200:
        print(f"✅ Activated: {workflow_id}")
    else:
        print(f"❌ Failed to activate: {response.text}")

# Usage
workflow_id = import_workflow('simple-query-ultraclean.json')
if workflow_id:
    activate_workflow(workflow_id)
```

**Method 3: Docker Volume Mount**

**Best for:** Version-controlled workflows, GitOps

**Steps:**
1. Create workflows directory:
   ```bash
   mkdir -p /docker/n8n/workflows
   cp simple-query-ultraclean.json /docker/n8n/workflows/
   ```

2. Mount in docker-compose.yml:
   ```yaml
   services:
     n8n:
       image: n8nio/n8n
       volumes:
         - /docker/n8n/data:/home/node/.n8n
         - /docker/n8n/workflows:/workflows:ro
   ```

3. Workflows auto-imported on container start

### Post-Deployment Validation

**Smoke Test:**
```bash
# Execute workflow via API
curl -X POST "https://n8n.uderia.com/api/v1/workflows/{id}/execute" \
  -H "X-N8N-API-KEY: $API_KEY"

# Check execution succeeded
curl -X GET "https://n8n.uderia.com/api/v1/executions/{execution_id}" \
  -H "X-N8N-API-KEY: $API_KEY" | jq '.finished'
```

**Monitor Logs:**
```bash
# n8n logs
docker logs -f n8n

# Uderia logs
docker logs -f uderia
```

---

## REST API vs UI Differences

### Profile Override Methods

**CRITICAL DISTINCTION:**

| Aspect | UI Method | REST API Method |
|--------|-----------|-----------------|
| **Syntax** | `@TAG query text` | `{"prompt": "query", "profile_id": "id"}` |
| **Example** | `@FOCUS Show me databases` | `{"prompt": "Show me databases", "profile_id": "profile-default-rag"}` |
| **Where Used** | Uderia web interface chat input | n8n workflows, Airflow DAGs, curl scripts |
| **How Parsed** | Frontend extracts @TAG, sends profile_id separately | profile_id is explicit parameter |
| **Empty Profile** | Omit @TAG entirely | `"profile_id": ""` or omit parameter |

**Why the Difference?**

The `@TAG` syntax is a **UI convenience feature** that:
1. Makes profile selection user-friendly in chat interface
2. Gets parsed by frontend JavaScript before API call
3. Converted to `profile_id` parameter before sending to backend

The REST API **never sees** the `@TAG` syntax - it only accepts `profile_id` as a parameter.

**Common Mistake:**

❌ **WRONG: Using @TAG syntax in n8n workflow**
```json
{
  "prompt": "@FOCUS Show me all databases available"
}
```

**Result:** Uderia treats "@FOCUS" as literal text in the query. Profile override does NOT happen.

✅ **CORRECT: Using profile_id parameter**
```json
{
  "prompt": "Show me all databases available",
  "profile_id": "profile-default-rag"
}
```

**Result:** Uderia correctly overrides to @FOCUS profile.

### Getting Profile IDs

**Method 1: REST API**
```bash
JWT=$(curl -s -X POST 'https://tda.uderia.com/api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Amadeu$01"}' | jq -r '.token')

curl -s -X GET 'https://tda.uderia.com/api/v1/profiles' \
  -H "Authorization: Bearer $JWT" | jq -r '.[] | "\(.tag): \(.id)"'
```

**Method 2: Uderia UI**
1. Navigate to Setup → Profiles
2. Click on profile row
3. Copy ID from URL: `/profiles/{id}`

**Example Profile IDs (from user system):**
```
@FOCUS: profile-default-rag
@OPTIM: profile-1764006444002-z0hdduce9
@ADVQL: profile-1764007169002-hqg2jrfcv
@CHAT: profile-1764006488002-44gwfzcgu
@OPTML: profile-1764007214002-2r76vxq92
@GENIE: profile-1764017195002-p4jnjgfp1
```

### Parameter Handling in Code Nodes

**Conditional Parameter Inclusion:**

Some REST API parameters are optional. Include them only when specified:

```javascript
// ✅ CORRECT: Conditional inclusion
const result = {
  prompt: query
};

if (profileId) {
  result.profile_id = profileId;  // Only add if non-empty
}

return { json: result };
```

```javascript
// ❌ WRONG: Always include empty string
const result = {
  prompt: query,
  profile_id: profileId || ""  // Sends empty string to API
};

return { json: result };
```

**Why it matters:** Uderia API treats `profile_id: ""` differently than omitted parameter. Empty string may trigger validation errors.

---

## Common Pitfalls & Solutions

### Pitfall 1: "Could not find property option" Error

**Symptom:**
- Workflow imports via API
- Opening in UI shows red error banner
- Cannot edit or execute workflow

**Cause:**
- n8n bug #23620: API-created complex workflows fail to render
- n8n bug #14775: Complex parameter structures cause errors

**Solution:**
1. Use **ultra-clean workflow pattern** (5-7 nodes, linear flow)
2. **Import via UI** instead of API
3. Avoid complex conditionals, loops, and nested parameters
4. Use Code nodes instead of inline JavaScript expressions

**Example Fix:**
```
❌ Complex workflow (14 nodes):
   Trigger → Session → Query → Loop → Poll → Switch → If → Retry → Format

✅ Ultra-clean workflow (7 nodes):
   Trigger → Set Config → Prepare Prompt → Session → Query → Wait → Result
```

### Pitfall 2: Set Config Node Fields Don't Import

**Symptom:**
- Import workflow successfully
- Open Set Config node
- See "Currently no items exist"

**Cause:**
- n8n doesn't load `assignments` array from JSON on import
- Known limitation of n8n import system

**Solution:**
**Manually configure after import:**
1. Click "Set Config" node
2. Click "Add Field" button
3. Add Field 1:
   - Name: `profile_id`
   - Type: String
   - Value: (leave empty for default profile)
4. Add Field 2:
   - Name: `query`
   - Type: String
   - Value: `Show me all databases available`
5. Click "Save"

**Prevention:**
- Document manual configuration steps in deployment guide
- Provide screenshots showing correct field setup
- Consider using Environment Variables for defaults

### Pitfall 3: "405 Not Allowed" from Uderia

**Symptom:**
```
Error: 405 Not Allowed
<html><head><title>405 Not Allowed</title></head>...
```

**Cause:**
- Wrong hostname in workflow URLs
- Common mistake: Using `https://uderia.com` instead of `https://tda.uderia.com`
- Reverse proxy rejects requests to wrong hostname

**Solution:**
1. Check reverse proxy configuration for correct source hostname
2. Update all HTTP Request node URLs to match:
   ```
   ❌ https://uderia.com/api/v1/sessions
   ✅ https://tda.uderia.com/api/v1/sessions
   ```

**How to find correct hostname:**
```bash
# Check reverse proxy config
# For Synology: Control Panel → Application Portal → Reverse Proxy
# Look for "Source" hostname field
```

### Pitfall 4: "invalid syntax" in JavaScript Expression

**Symptom:**
```
Error: invalid syntax
  at evaluate expression: {{ JSON.stringify(...) }}
```

**Cause:**
- Inline JavaScript expressions in n8n have limitations
- Complex logic (conditionals, object manipulation) fails
- `JSON.stringify()` in `jsonBody` parameter causes issues

**Solution:**
**Use Code node instead of inline expression:**

❌ **WRONG: Inline expression**
```json
{
  "jsonBody": "={{ JSON.stringify({ prompt: $('Set Config').item.json.query, profile_id: $('Set Config').item.json.profile_id }) }}"
}
```

✅ **CORRECT: Code node**
```javascript
const config = $input.first().json;

const result = {
  prompt: config.query
};

if (config.profile_id) {
  result.profile_id = config.profile_id;
}

return { json: result };
```

Then reference in HTTP Request node:
```json
{
  "jsonBody": "={{ $('Prepare Prompt').item.json }}"
}
```

### Pitfall 5: "Connection Lost" / WebSocket Errors

**Symptom:**
```
Connection Lost - Trying to reconnect...
WebSocket connection failed
ERR_CONNECTION_REFUSED
```

**Cause:**
- Reverse proxy missing WebSocket upgrade headers
- n8n requires WebSocket for real-time UI updates

**Solution:**
**Configure reverse proxy WebSocket support:**

**For nginx (Synology DSM):**
1. Open Application Portal → Reverse Proxy
2. Edit n8n rule
3. Go to "Custom Header" tab
4. Add headers:
   ```
   Header: Upgrade
   Value: $http_upgrade

   Header: Connection
   Value: upgrade
   ```
5. Save and restart proxy

**For nginx (direct config):**
```nginx
location / {
    proxy_pass http://localhost:5678;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

### Pitfall 6: Profile Override Not Working

**Symptom:**
- Set profile_id in workflow
- Result shows default profile, not override

**Cause:**
- Using `@TAG` syntax instead of `profile_id` parameter
- This is the **most critical mistake** in REST API usage

**Diagnosis:**
```bash
# Check result for profile_tag field
curl -X GET "https://tda.uderia.com/api/v1/tasks/{task_id}" \
  -H "Authorization: Bearer $JWT" | jq '.result.profile_tag'

# If shows default profile instead of expected override, check your request
```

**Solution:**
**Ensure using correct REST API method:**

❌ **WRONG:**
```json
{
  "prompt": "@FOCUS Show me databases"
}
```

✅ **CORRECT:**
```json
{
  "prompt": "Show me databases",
  "profile_id": "profile-default-rag"
}
```

**Verification:**
```javascript
// In Prepare Prompt Code node, log the output
console.log('Request body:', JSON.stringify(result));

// Should output:
// {"prompt": "Show me databases", "profile_id": "profile-default-rag"}
```

### Pitfall 7: 401 Unauthorized Errors

**Symptom:**
```
Error: 401 Unauthorized
{"error": "Invalid token"}
```

**Causes:**
1. Token expired (90-day access token or 24-hour JWT)
2. Wrong credential selected in HTTP Request node
3. Malformed Authorization header

**Solution:**

**Check 1: Verify token validity**
```bash
curl -X GET "https://tda.uderia.com/api/v1/sessions" \
  -H "Authorization: Bearer $TOKEN"

# If 401, regenerate token
```

**Check 2: Verify credential configuration**
1. Open n8n workflow
2. Click HTTP Request node
3. Check Authentication section:
   - Type: Predefined Credential Type
   - Credential Type: Header Auth
   - Credential: Uderia API Token
4. Test credential:
   - Click "Credential" dropdown
   - Click gear icon next to credential
   - Click "Test" button

**Check 3: Verify header format**
```
Header Name: Authorization
Header Value: Bearer tda_u9aSO6khhXTsb7QoQiaylq2121ck-Tvm
                     ↑
                  Required space after "Bearer"
```

### Pitfall 8: Docker Networking Issues

**Symptom:**
```
Error: connect ECONNREFUSED 127.0.0.1:5050
Error: getaddrinfo ENOTFOUND uderia
```

**Cause:**
- n8n container can't reach Uderia container
- Common with containers on different Docker networks

**Diagnosis:**
```bash
# Check container networks
docker inspect uderia | jq '.[0].NetworkSettings.Networks'
docker inspect n8n | jq '.[0].NetworkSettings.Networks'

# If different networks, containers can't communicate directly
```

**Solution:**

**Option 1: Use host IP (works across networks)**
```
URLs: http://192.168.1.100:5050/api/v1
```

**Option 2: Connect containers to same network**
```bash
# Create shared network
docker network create uderia_network

# Connect containers
docker network connect uderia_network uderia
docker network connect uderia_network n8n
```

Then use container name:
```
URLs: http://uderia:5050/api/v1
```

**Option 3: Use docker-compose**
```yaml
version: '3'

networks:
  uderia_network:

services:
  uderia:
    image: uderia:latest
    networks:
      - uderia_network
    ports:
      - "5050:5050"

  n8n:
    image: n8nio/n8n
    networks:
      - uderia_network
    environment:
      - N8N_HOST: https://n8n.uderia.com
```

---

## Docker Networking

### Understanding Container Networking

**Network Types:**

| Type | Description | Use Case |
|------|-------------|----------|
| **bridge** | Default network, containers isolated | Single-host, basic isolation |
| **host** | Container uses host network stack | High performance, no isolation |
| **custom** | User-defined bridge | Multi-container apps, service discovery |

### Common Scenario: Containers on Different Networks

**Problem:**
```
Uderia: TDA_Network (192.168.1.0/24)
n8n:    bridge (172.17.0.0/16)

n8n → uderia:5050 ❌ (DNS fails)
n8n → localhost:5050 ❌ (wrong container)
n8n → 127.0.0.1:5050 ❌ (wrong container)
```

**Solution: Use Host IP**
```
n8n → 192.168.1.100:5050 ✅ (host IP, works across networks)
```

**Why it works:**
- Host IP is accessible from all Docker networks
- Port 5050 published to host (docker run -p 5050:5050)
- Firewall allows localhost → localhost traffic

### Finding Host IP

```bash
# Method 1: ip command
ip addr show | grep inet

# Method 2: hostname command
hostname -I

# Method 3: Docker inspect
docker inspect uderia | jq '.[0].NetworkSettings.Networks'
```

### Configuring n8n for Cross-Network Communication

**Update workflow URLs:**
```json
{
  "url": "http://192.168.1.100:5050/api/v1/sessions"
}
```

**Or use environment variable:**
```bash
docker run -d \
  -e UDERIA_BASE_URL=http://192.168.1.100:5050 \
  n8nio/n8n
```

Then in workflow:
```json
{
  "url": "={{ $env.UDERIA_BASE_URL }}/api/v1/sessions"
}
```

### Production: Use Reverse Proxy

**Best practice: Access both via domain names**

```
n8n → https://tda.uderia.com/api/v1 (via reverse proxy)
```

**Benefits:**
- No hardcoded IPs
- SSL/TLS termination
- Load balancing
- WebSocket support

---

## Reverse Proxy Configuration

### Synology DSM Reverse Proxy

**Configuration for n8n:**

1. **Source:**
   - Protocol: HTTPS
   - Hostname: n8n.uderia.com
   - Port: 443

2. **Destination:**
   - Protocol: HTTP
   - Hostname: localhost
   - Port: 5678

3. **Custom Headers:**
   ```
   Upgrade: $http_upgrade
   Connection: upgrade
   ```

**Configuration for Uderia:**

1. **Source:**
   - Protocol: HTTPS
   - Hostname: tda.uderia.com
   - Port: 443

2. **Destination:**
   - Protocol: HTTP
   - Hostname: localhost
   - Port: 5050

### nginx Direct Configuration

**Full nginx.conf example:**

```nginx
upstream n8n {
    server localhost:5678;
}

upstream uderia {
    server localhost:5050;
}

server {
    listen 443 ssl;
    server_name n8n.uderia.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://n8n;
        proxy_http_version 1.1;

        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Standard headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 443 ssl;
    server_name tda.uderia.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://uderia;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Testing Reverse Proxy

**Test n8n WebSocket:**
```bash
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: test" \
  https://n8n.uderia.com/
```

**Expected:** 101 Switching Protocols

**Test Uderia REST API:**
```bash
curl -X POST https://tda.uderia.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Amadeu$01"}'
```

**Expected:** 200 OK with JWT token

---

## Reference Examples

### Example 1: Simple Query Workflow (Complete)

**File:** `simple-query-ultraclean.json`

**Purpose:** Manual trigger workflow with profile override support

**Node Breakdown:**

**1. Manual Trigger**
- Type: `n8n-nodes-base.manualTrigger`
- Config: None
- Output: Empty JSON object `{}`

**2. Set Config**
- Type: `n8n-nodes-base.set`
- Config: Assignments array with profile_id and query
- Output: `{ profile_id: "", query: "Show me all databases available" }`

**3. Prepare Prompt (Code Node)**
```javascript
const config = $input.first().json;
const profileId = config.profile_id || '';
const query = config.query || '';

const result = {
  prompt: query
};

if (profileId) {
  result.profile_id = profileId;
}

return { json: result };
```
- Input: Set Config output
- Output: `{ prompt: "...", profile_id: "..." }` (only if profileId non-empty)

**4. Create Session**
- Type: `n8n-nodes-base.httpRequest`
- Method: POST
- URL: `https://tda.uderia.com/api/v1/sessions`
- Auth: Uderia API Token
- Output: `{ session_id: "session_1234567890" }`

**5. Submit Query**
- Type: `n8n-nodes-base.httpRequest`
- Method: POST
- URL: `=https://tda.uderia.com/api/v1/sessions/{{ $json.session_id }}/query`
- Body: `={{ $('Prepare Prompt').item.json }}`
- Auth: Uderia API Token
- Output: `{ task_id: "task_1234567890" }`

**6. Wait**
- Type: `n8n-nodes-base.wait`
- Duration: 8 seconds
- Output: Passes through task_id

**7. Get Result**
- Type: `n8n-nodes-base.httpRequest`
- Method: GET
- URL: `=https://tda.uderia.com/api/v1/tasks/{{ $json.task_id }}`
- Auth: Uderia API Token
- Output: Full task result with `final_answer`, `profile_tag`, token counts

**Full JSON:** See `docs/n8n/workflows/simple-query-ultraclean.json`

### Example 2: Scheduled Report Workflow

**File:** `scheduled-report-ultraclean.json`

**Purpose:** Daily automated report generation

**Key Differences from Simple Query:**

**1. Schedule Trigger (instead of Manual)**
```json
{
  "parameters": {
    "rule": {
      "interval": [{
        "field": "cronExpression",
        "expression": "0 8 * * *"
      }]
    }
  },
  "type": "n8n-nodes-base.scheduleTrigger"
}
```

**2. Hardcoded Query (no Set Config)**
```json
{
  "jsonBody": "{\"prompt\": \"Generate a daily inventory report showing all products with quantity below 10 units\"}"
}
```

**3. Format Report (Code Node)**
```javascript
const result = $json.result || {};
const answer = result.final_answer_text || result.final_answer || 'No report generated';

return {
  json: {
    report: answer,
    tokens: (result.turn_input_tokens || 0) + (result.turn_output_tokens || 0)
  }
};
```

**4. Longer Wait Time**
```json
{
  "parameters": {
    "amount": 10,
    "unit": "seconds"
  }
}
```

**Use Cases:**
- Daily inventory reports
- Weekly sales summaries
- Monthly compliance checks
- Automated data quality audits

### Example 3: Slack Integration Workflow

**File:** `slack-integration-ultraclean.json`

**Purpose:** Respond to Slack slash commands

**Key Features:**

**1. Webhook Trigger**
```json
{
  "parameters": {
    "httpMethod": "POST",
    "path": "uderia-slack",
    "responseMode": "lastNode"
  },
  "type": "n8n-nodes-base.webhook"
}
```

**2. Parse Slack Command (Code Node)**
```javascript
const text = $json.body?.text || '';
const userId = $json.body?.user_name || 'unknown';

return {
  json: {
    prompt: text,
    user: userId,
    responseUrl: $json.body?.response_url
  }
};
```

**3. Format Response (Code Node)**
```javascript
const result = $json.result || {};
const answer = result.final_answer_text || result.final_answer || 'No answer available';

// Truncate to Slack message limit
return {
  json: {
    text: answer.substring(0, 2800)
  }
};
```

**Slack Command Setup:**
1. Create Slack App
2. Add Slash Command: `/uderia`
3. Request URL: `https://n8n.uderia.com/webhook/uderia-slack`
4. Install to workspace

**Usage:**
```
/uderia Show me all products with low inventory
```

---

## Troubleshooting Guide

### Diagnostic Commands

**Check n8n Status:**
```bash
docker ps | grep n8n
docker logs n8n --tail 50
curl -I https://n8n.uderia.com
```

**Check Uderia Status:**
```bash
docker ps | grep uderia
docker logs uderia --tail 50
curl -I https://tda.uderia.com
```

**Test Network Connectivity (from n8n container):**
```bash
docker exec -it n8n sh
ping 192.168.1.100
wget -O- http://192.168.1.100:5050/api/v1/health
```

**Test Authentication:**
```bash
JWT=$(curl -s -X POST 'https://tda.uderia.com/api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Amadeu$01"}' | jq -r '.token')

echo "JWT: ${JWT:0:50}..."

# If JWT is null, check credentials
```

**Test Session Creation:**
```bash
curl -v -X POST 'https://tda.uderia.com/api/v1/sessions' \
  -H "Authorization: Bearer $JWT"

# Check for:
# - 200 OK status
# - { "session_id": "..." } in response
# - No 401, 400, or 500 errors
```

### Common Error Messages

**Error: "No default profile configured"**
```json
{
  "error": "No default profile configured for user"
}
```

**Solution:**
1. Login to Uderia UI
2. Go to Setup → Profiles
3. Click on any profile row
4. Click "Set as Default" button
5. Retry workflow

**Error: "Task not found"**
```json
{
  "error": "Task not found"
}
```

**Cause:** Polling too quickly after submit

**Solution:** Increase Wait node duration (8-10 seconds)

**Error: "WebSocket connection failed"**
```
ERR_DISALLOWED_URL_SCHEME
WebSocket connection to 'ws://localhost:5678' failed
```

**Solution:** Add WebSocket headers to reverse proxy (see Reverse Proxy Configuration section)

**Error: "Header name must be a valid HTTP token"**
```
Error: Header name must be a valid HTTP token ["Uderia API Token"]
```

**Solution:** Use "Authorization" as header name, not credential name

### Debug Workflow Execution

**Enable n8n Debug Mode:**
```bash
docker run -d \
  -e EXECUTIONS_DATA_SAVE_ON_ERROR=all \
  -e EXECUTIONS_DATA_SAVE_ON_SUCCESS=all \
  -e EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=true \
  n8nio/n8n
```

**View Execution Data:**
1. Click "Executions" tab in n8n
2. Find failed execution
3. Click to view node-by-node output
4. Check "Error" column for failure details

**Export Execution for Analysis:**
```bash
curl -X GET "https://n8n.uderia.com/api/v1/executions/{id}" \
  -H "X-N8N-API-KEY: $API_KEY" > execution.json

# Analyze with jq
cat execution.json | jq '.data.resultData.runData'
```

---

## Advanced Topics

### Session Reuse for Multi-Turn Conversations

**Pattern:** Keep session_id alive for follow-up queries

**Workflow Modifications:**

**1. Store Session ID in Global Variable**
```javascript
// After Create Session node
const sessionId = $json.session_id;

// Set global variable
await $globals.set('uderia_session_id', sessionId);

return { json: { session_id: sessionId } };
```

**2. Reuse Session for Next Query**
```javascript
// Before Submit Query node
const sessionId = await $globals.get('uderia_session_id') || null;

if (!sessionId) {
  throw new Error('No active session. Create session first.');
}

return { json: { session_id: sessionId } };
```

**Benefits:**
- Context maintained across queries
- Faster execution (no session creation)
- Conversation history preserved

**Limitations:**
- Session expires after 24 hours of inactivity
- Context window limits (~100K tokens)

### Profile Switching Within Workflow

**Pattern:** Use different profiles for different workflow steps

**Example: Use @FOCUS for query, @CHAT for summary**

**Step 1: Execute Query with @FOCUS**
```javascript
// Prepare Prompt node
return {
  json: {
    prompt: "Show me all products with low inventory",
    profile_id: "profile-default-rag"  // @FOCUS
  }
};
```

**Step 2: Create Second Session with @CHAT**
```json
{
  "method": "POST",
  "url": "https://tda.uderia.com/api/v1/sessions"
}
```

**Step 3: Submit Summary Query with @CHAT**
```javascript
// Prepare Summary node
const queryResult = $('Get Result').item.json.result.final_answer;

return {
  json: {
    prompt: `Summarize this data in 3 bullet points: ${queryResult}`,
    profile_id: "profile-1764006488002-44gwfzcgu"  // @CHAT
  }
};
```

**Use Cases:**
- Technical query → Human-readable summary
- Data retrieval → Report generation
- Complex analysis → Executive brief

### Token Usage Tracking

**Pattern:** Monitor LLM costs across workflows

**Extract Token Counts:**
```javascript
// After Get Result node
const result = $json.result;

const tokenData = {
  input_tokens: result.turn_input_tokens || 0,
  output_tokens: result.turn_output_tokens || 0,
  total_tokens: (result.turn_input_tokens || 0) + (result.turn_output_tokens || 0),
  profile_tag: result.profile_tag,
  session_id: $json.session_id,
  task_id: $json.task_id
};

return { json: tokenData };
```

**Store in Database:**
```json
{
  "node": "Postgres",
  "parameters": {
    "operation": "insert",
    "table": "uderia_usage",
    "columns": "session_id,task_id,profile_tag,input_tokens,output_tokens,total_tokens",
    "values": "={{ $json.session_id }},={{ $json.task_id }},={{ $json.profile_tag }},={{ $json.input_tokens }},={{ $json.output_tokens }},={{ $json.total_tokens }}"
  }
}
```

**Create Cost Dashboard:**
```sql
-- Daily token usage by profile
SELECT
  DATE(created_at) as date,
  profile_tag,
  SUM(total_tokens) as total_tokens,
  COUNT(*) as query_count
FROM uderia_usage
GROUP BY DATE(created_at), profile_tag
ORDER BY date DESC;
```

### Error Handling & Retries

**Pattern:** Gracefully handle Uderia API failures

**Add Error Handling to Submit Query:**
```javascript
// Error Handler Code node
const error = $input.all()[0].json.error;

if (error.message.includes('401')) {
  // Token expired
  return {
    json: {
      action: 'refresh_token',
      message: 'Access token expired. Please regenerate.'
    }
  };
} else if (error.message.includes('400')) {
  // Bad request
  return {
    json: {
      action: 'fix_request',
      message: 'Invalid request. Check profile_id and prompt format.'
    }
  };
} else {
  // Unknown error
  return {
    json: {
      action: 'alert',
      message: `Unexpected error: ${error.message}`
    }
  };
}
```

**Add Retry Logic:**
```javascript
// Retry Logic node
const maxRetries = 3;
const currentRetry = await $globals.get('retry_count') || 0;

if (currentRetry < maxRetries) {
  await $globals.set('retry_count', currentRetry + 1);

  // Wait before retry (exponential backoff)
  await new Promise(resolve => setTimeout(resolve, Math.pow(2, currentRetry) * 1000));

  return { json: { retry: true } };
} else {
  await $globals.set('retry_count', 0);
  return { json: { retry: false, error: 'Max retries exceeded' } };
}
```

---

## Best Practices

### Workflow Design

1. **Keep it linear**: Avoid complex loops and conditionals
2. **Use Code nodes**: For any logic beyond simple variable substitution
3. **Explicit parameters**: Don't rely on inline expressions for critical logic
4. **Descriptive names**: Name nodes clearly (e.g., "Prepare Prompt" not "Code 1")
5. **Comment complex logic**: Add comments in Code nodes explaining the approach

### Security

1. **Never hardcode tokens**: Use credentials manager
2. **Use access tokens**: Not JWTs (longer expiry, designed for automation)
3. **Rotate tokens**: Set 90-day expiry, automate rotation
4. **Encrypt at rest**: n8n credentials encrypted by default
5. **HTTPS only**: Production workflows should only use HTTPS endpoints

### Performance

1. **Reuse sessions**: For multi-turn conversations in same workflow
2. **Batch queries**: If running multiple queries, create session once
3. **Optimize wait times**: Start with 8s, increase only if needed
4. **Monitor token usage**: Track costs, optimize prompts
5. **Use appropriate profiles**: @CHAT for simple queries, @FOCUS for complex
6. **Model selection for MCP prompts**: For structured MCP prompt execution (e.g., `Executing prompt: qlty_databaseQuality`), lower-intelligence models (Llama-3.3-70B) often outperform higher-intelligence models (Claude Sonnet) with 80% cost savings and 26% fewer tokens. Orchestrator-driven architecture reduces LLM reasoning requirements. See fusion-hardening skill Section 5.1 for detailed guidance on when to use lower vs higher intelligence models

### Maintainability

1. **Version control workflows**: Export JSON, commit to git
2. **Document profile IDs**: Keep list of profile IDs in README
3. **Test before deploy**: Always test in local environment first
4. **Monitor executions**: Set up alerts for failed workflows
5. **Keep workflows simple**: If >10 nodes, consider splitting

---

## Appendix

### Complete n8n Environment Variables

```bash
# Required
N8N_HOST=https://n8n.uderia.com
WEBHOOK_URL=https://n8n.uderia.com/
N8N_PROTOCOL=https

# Optional but recommended
N8N_PORT=5678
EXECUTIONS_DATA_SAVE_ON_ERROR=all
EXECUTIONS_DATA_SAVE_ON_SUCCESS=all
EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=true

# Security
N8N_BASIC_AUTH_ACTIVE=true
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=secure_password

# Database (optional, for persistence)
DB_TYPE=postgresdb
DB_POSTGRESDB_HOST=postgres
DB_POSTGRESDB_PORT=5432
DB_POSTGRESDB_DATABASE=n8n
DB_POSTGRESDB_USER=n8n
DB_POSTGRESDB_PASSWORD=secure_password
```

### Complete Docker Run Command

```bash
docker run -d \
  --name n8n \
  --network uderia_network \
  -p 5678:5678 \
  -e N8N_HOST=https://n8n.uderia.com \
  -e WEBHOOK_URL=https://n8n.uderia.com/ \
  -e N8N_PROTOCOL=https \
  -e EXECUTIONS_DATA_SAVE_ON_ERROR=all \
  -e EXECUTIONS_DATA_SAVE_ON_SUCCESS=all \
  -e N8N_BASIC_AUTH_ACTIVE=true \
  -e N8N_BASIC_AUTH_USER=admin \
  -e N8N_BASIC_AUTH_PASSWORD=secure_password \
  -v /docker/n8n/data:/home/node/.n8n \
  -v /docker/n8n/workflows:/workflows:ro \
  --restart unless-stopped \
  n8nio/n8n
```

### Docker Compose Configuration

```yaml
version: '3.8'

networks:
  uderia_network:
    external: true

services:
  n8n:
    image: n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    networks:
      - uderia_network
    ports:
      - "5678:5678"
    environment:
      - N8N_HOST=https://n8n.uderia.com
      - WEBHOOK_URL=https://n8n.uderia.com/
      - N8N_PROTOCOL=https
      - EXECUTIONS_DATA_SAVE_ON_ERROR=all
      - EXECUTIONS_DATA_SAVE_ON_SUCCESS=all
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=admin
      - N8N_BASIC_AUTH_PASSWORD=${N8N_PASSWORD}
    volumes:
      - /docker/n8n/data:/home/node/.n8n
      - /docker/n8n/workflows:/workflows:ro
```

### Uderia Profile IDs Reference

**From user system (as of 2026-02-09):**

| Tag | Profile ID | Description |
|-----|------------|-------------|
| `@FOCUS` | `profile-default-rag` | RAG-focused knowledge search |
| `@OPTIM` | `profile-1764006444002-z0hdduce9` | Tool-enabled optimizer |
| `@ADVQL` | `profile-1764007169002-hqg2jrfcv` | Advanced SQL queries |
| `@CHAT` | `profile-1764006488002-44gwfzcgu` | Conversational LLM |
| `@OPTML` | `profile-1764007214002-2r76vxq92` | Optimized LLM config |
| `@GENIE` | `profile-1764017195002-p4jnjgfp1` | Multi-profile coordinator |

**Get current list via API:**
```bash
curl -X GET 'https://tda.uderia.com/api/v1/profiles' \
  -H "Authorization: Bearer $JWT" | jq -r '.[] | "\(.tag): \(.id)"'
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-09 | Initial comprehensive guide |

---

## Support & Resources

**Documentation:**
- Uderia REST API: `docs/RestAPI/restAPI.md`
- n8n Workflows: `docs/n8n/WORKFLOW_TEMPLATES.md`
- Import Guide: `docs/n8n/IMPORT_STATUS.md`
- Quickstart: `docs/n8n/QUICKSTART.md`

**Example Workflows:**
- Simple Query: `docs/n8n/workflows/simple-query-ultraclean.json`
- Scheduled Report: `docs/n8n/workflows/scheduled-report-ultraclean.json`
- Slack Integration: `docs/n8n/workflows/slack-integration-ultraclean.json`

**External Resources:**
- n8n Documentation: https://docs.n8n.io
- n8n Community: https://community.n8n.io
- n8n Bug #23620: https://github.com/n8n-io/n8n/issues/23620
- n8n Bug #14775: https://github.com/n8n-io/n8n/issues/14775

**Uderia Support:**
- GitHub: https://github.com/yourusername/uderia
- Documentation: `docs/`

---

**End of n8n + Uderia Integration Guide v1.0**
