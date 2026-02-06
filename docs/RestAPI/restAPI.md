# Uderia Platform REST API Documentation

## Table of Contents

1. [Introduction](#1-introduction)
2. [Authentication](#2-authentication)
   - [Access Tokens (Recommended)](#21-access-tokens-recommended)
   - [JWT Tokens](#22-jwt-tokens)
   - [Quick Start Guide](#23-quick-start-guide)
3. [API Endpoints](#3-api-endpoints)
   - [Authentication Endpoints](#31-authentication-endpoints)
   - [Access Token Management](#32-access-token-management)
   - [Application Configuration](#33-application-configuration)
   - [Session Management](#34-session-management)
   - [Query Execution](#35-query-execution)
   - [Task Management](#36-task-management)
   - [RAG Collection Management](#37-rag-collection-management)
   - [RAG Template System](#38-rag-template-system)
   - [MCP Server Management](#39-mcp-server-management)
   - [Profile Management](#310-profile-management)
   - [Session Analytics](#311-session-analytics)
   - [System Prompts Management](#312-system-prompts-management)
   - [Document Upload](#313-document-upload)
   - [Agent Pack Management](#314-agent-pack-management)
4. [Data Models](#4-data-models)
5. [Code Examples](#5-code-examples)
6. [Security Best Practices](#6-security-best-practices)
7. [Troubleshooting](#7-troubleshooting)
8. [Quick Reference](#8-quick-reference)
9. [API Updates & Migration Notes](#9-api-updates--migration-notes)
10. [Additional Resources](#10-additional-resources)

---

## 1. Introduction

Welcome to the Uderia Platform (TDA) REST API. This API provides a programmatic interface to interact with the agent's powerful data analysis and querying capabilities.

The API is designed around an **asynchronous task-based architecture**. This pattern is ideal for handling potentially long-running agent processes in a robust and scalable way. Instead of holding a connection open while the agent works, you initiate a task and then poll a status endpoint to get progress updates and the final result. You can also cancel a running task if needed.

### Key Features

- **🔐 Secure Authentication**: Dual authentication system with JWT and long-lived access tokens
- **⚡ Asynchronous Query Execution**: Submit queries and poll for results without holding connections
- **🧠 RAG Collection Management**: Create and manage collections of query patterns for context-aware responses
- **📝 Template-Based Population**: Use modular templates to automatically generate RAG case studies
- **🤖 LLM-Assisted Generation**: Generate question/SQL pairs automatically from database schemas
- **🔌 MCP Server Integration**: Connect to multiple Model Context Protocol servers for data access
- **💬 Session Management**: Maintain conversation context across multiple queries
- **📊 Analytics & Monitoring**: Track token usage, costs, and performance metrics

### Base URL

All API endpoints are relative to your TDA instance:
```
http://your-tda-host:5050/api
```

For local development:
```
http://localhost:5050/api
http://127.0.0.1:5050/api
```

### Prerequisites for REST API

⚠️ **Important:** Before you can use REST endpoints for session creation or query execution, you must:

1. **Authenticate** - Login and obtain an access token (JWT or long-lived token)
2. **Configure Profile** - Create a profile that combines:
   - An **LLM Provider** (Google, Anthropic, Azure, AWS, Friendli, or Ollama)
   - An **MCP Server** (your data source and tools)
3. **Set as Default** - Mark your profile as the default for your user account

Without a configured default profile, REST endpoints will return `400 Bad Request` with a helpful error message.

### Quick Start Workflow

The typical REST API workflow involves five steps:

**1. Authenticate** - Obtain a JWT from `/auth/login`, then create long-lived token via `/auth/tokens`  
**2. Create Profile** (One-time) - Configure LLM + MCP via UI or REST endpoints, set as default  
**3. Create a Session** - `POST /api/v1/sessions` to start a conversation context  
**4. Submit a Query** - `POST /api/v1/sessions/{session_id}/query` with your prompt  
**5. Poll for Results** - `GET /api/v1/tasks/{task_id}` to check status and retrieve results  

```bash
# 1. Login to get JWT (one-time or per session)
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your_password"}' | jq -r '.access_token')

# 2. Create access token for API automation (one-time)
TOKEN=$(curl -s -X POST http://localhost:5050/api/v1/auth/tokens \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"my_app","expires_in_days":90}' | jq -r '.token')

# Note: Configure Profile in UI or API (set LLM + MCP, mark as default)

# 3. Create session (uses your default profile)
SESSION=$(curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN")
SESSION_ID=$(echo $SESSION | jq -r '.session_id')

# 4. Submit query
TASK=$(curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Show me available databases"}')
TASK_ID=$(echo $TASK | jq -r '.task_id')

# 5. Check result
curl -s http://localhost:5050/api/v1/tasks/$TASK_ID \
  -H "Authorization: Bearer $TOKEN" | jq '.result'
```

---

## 2. Authentication

The Uderia Platform REST API requires authentication for all endpoints except public registration. We support two authentication methods optimized for different use cases.

### 2.1. Access Tokens (Recommended)

**Best for:** REST API clients, automation scripts, CI/CD pipelines, external integrations

Access tokens are **long-lived API keys** that provide secure programmatic access without exposing credentials.

#### Features

✅ **Long-lived** - Configurable expiration (30/60/90/180/365 days) or never expires  
✅ **Secure** - SHA256 hashed storage, shown only once on creation  
✅ **Trackable** - Monitor usage count and last used timestamp  
✅ **Revocable** - Instantly revoke compromised tokens  
✅ **Multiple tokens** - Create separate tokens per application/environment  
✅ **Named** - Descriptive names for easy management (e.g., "Production Server")

#### Token Format

```
tda_<32-random-characters>
```

Example: `tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p`

#### Using Access Tokens

Include the token in the `Authorization` header with the `Bearer` scheme:

```bash
curl -X GET http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p"
```

### 2.2. JWT Tokens

**Best for:** Web UI sessions, interactive applications, short-term access

JWT (JSON Web Tokens) are short-lived session tokens automatically managed by the web interface.

#### Features

✅ **Auto-expiration** - 24-hour lifetime  
✅ **Stateless** - No server-side session storage  
✅ **Automatic** - Managed by web UI  

#### Using JWT Tokens

```bash
# Login to get JWT token
JWT=$(curl -s -X POST http://localhost:5050/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"your_username","password":"your_password"}' \
  | jq -r '.token')

# Use JWT token in API calls
curl -X GET http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $JWT"
```

### 2.3. Quick Start Guide

#### Step 1: Register an Account

```bash
curl -X POST http://localhost:5050/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "api_user",
    "email": "user@example.com",
    "password": "SecurePassword123!"
  }'
```

**Response:**
```json
{
  "status": "success",
  "message": "User registered successfully",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "api_user",
    "email": "user@example.com"
  }
}
```

#### Step 2: Login to Get JWT Token

```bash
curl -X POST http://localhost:5050/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "api_user",
    "password": "SecurePassword123!"
  }'
```

**Response:**
```json
{
  "status": "success",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "api_user",
    "email": "user@example.com",
    "user_uuid": "api_user_550e8400"
  }
}
```

#### Step 3: Create an Access Token

```bash
JWT="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

curl -X POST http://localhost:5050/api/v1/auth/tokens \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production Server",
    "expires_in_days": 90
  }'
```

**Response:**
```json
{
  "status": "success",
  "token": "tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p",
  "token_id": "abc123-def456-ghi789",
  "name": "Production Server",
  "created_at": "2025-11-25T10:00:00Z",
  "expires_at": "2026-02-25T10:00:00Z"
}
```

⚠️ **CRITICAL:** Copy the `token` value immediately! It cannot be retrieved later.

#### Step 4: Use Your Access Token

```bash
TOKEN="tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p"

curl -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN"
```

---

## 3. API Endpoints

The base URL for all endpoints is `/api`.

### 3.1. Authentication Endpoints

#### 3.1.1. Register User

Create a new user account.

**Endpoint:** `POST /auth/register`  
**Authentication:** None (public endpoint)

**Request Body:**
```json
{
  "username": "api_user",
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

**Validation Rules:**
- `username`: 3-50 characters, alphanumeric and underscores only
- `email`: Valid email format
- `password`: Minimum 8 characters

**Success Response:**
```json
{
  "status": "success",
  "message": "User registered successfully",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "api_user",
    "email": "user@example.com"
  }
}
```

**Error Responses:**
- `400 Bad Request` - Validation failed or username/email already exists
- `429 Too Many Requests` - Rate limit exceeded (3 registrations per hour per IP)

#### 3.1.2. Login

Authenticate and receive a JWT token.

**Endpoint:** `POST /auth/login`  
**Authentication:** None (uses credentials)

**Request Body:**
```json
{
  "username": "api_user",
  "password": "SecurePassword123!"
}
```

**Success Response:**
```json
{
  "status": "success",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "api_user",
    "email": "user@example.com",
    "user_uuid": "api_user_550e8400"
  }
}
```

**Error Responses:**
- `401 Unauthorized` - Invalid username or password
- `429 Too Many Requests` - Rate limit exceeded (5 attempts per minute per IP)

**Token Lifetime:** 24 hours

#### 3.1.3. Logout

Invalidate the current JWT token (web UI only - access tokens should be revoked via API).

**Endpoint:** `POST /auth/logout`  
**Authentication:** Required (JWT token)

**Success Response:**
```json
{
  "status": "success",
  "message": "Logged out successfully"
}
```

### 3.2. Access Token Management

#### 3.2.1. Create Access Token

Generate a new long-lived access token for API authentication.

**Endpoint:** `POST /api/v1/auth/tokens`  
**Authentication:** Required (JWT or access token)

**Request Body:**
```json
{
  "name": "Production Server",
  "expires_in_days": 90
}
```

**Parameters:**
- `name` (string, required): Descriptive name for the token (3-100 characters)
- `expires_in_days` (integer, optional): Expiration in days (30/60/90/180/365) or `null` for never

**Success Response:**
```json
{
  "status": "success",
  "token": "tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p",
  "token_id": "abc123-def456-ghi789",
  "name": "Production Server",
  "created_at": "2025-11-25T10:00:00Z",
  "expires_at": "2026-02-25T10:00:00Z"
}
```

⚠️ **Security Note:** The full token is shown **only once**. Store it securely immediately.

**Error Responses:**
- `400 Bad Request` - Invalid parameters
- `401 Unauthorized` - Authentication required

#### 3.2.2. List Access Tokens

Retrieve all access tokens for the authenticated user.

**Endpoint:** `GET /api/v1/auth/tokens`  
**Authentication:** Required (JWT or access token)

**Query Parameters:**
- `include_revoked` (boolean, optional): Include revoked tokens in response (default: `false`)

**Success Response:**
```json
{
  "status": "success",
  "tokens": [
    {
      "id": "abc123-def456-ghi789",
      "name": "Production Server",
      "token_prefix": "tda_1a2b3c...",
      "created_at": "2025-11-25T10:00:00Z",
      "last_used_at": "2025-11-25T14:30:00Z",
      "expires_at": "2026-02-25T10:00:00Z",
      "revoked": false,
      "revoked_at": null,
      "use_count": 142
    },
    {
      "id": "xyz789-uvw456-rst123",
      "name": "Development",
      "token_prefix": "tda_9z8y7x...",
      "created_at": "2025-11-20T09:00:00Z",
      "last_used_at": null,
      "expires_at": null,
      "revoked": true,
      "revoked_at": "2025-11-24T16:00:00Z",
      "use_count": 23
    }
  ]
}
```

**Token Fields:**
- `token_prefix`: First 10 characters for identification
- `last_used_at`: `null` if never used
- `expires_at`: `null` if no expiration
- `revoked`: Boolean indicating if token has been revoked
- `revoked_at`: Timestamp when token was revoked, `null` if active
- `use_count`: Total number of API calls with this token

**Note:** By default, only active tokens are returned. Set `include_revoked=true` to see revoked tokens in the audit trail.

#### 3.2.3. Revoke Access Token

Immediately revoke an access token, preventing further use. The token is marked as revoked and preserved in the audit trail.

**Endpoint:** `DELETE /api/v1/auth/tokens/{token_id}`  
**Authentication:** Required (JWT or access token)

**URL Parameters:**
- `token_id` (string, required): The token ID to revoke

**Success Response:**
```json
{
  "status": "success",
  "message": "Token revoked successfully"
}
```

**Error Responses:**
- `404 Not Found` - Token not found or doesn't belong to user
- `401 Unauthorized` - Authentication required

⚠️ **Note:** Revoked tokens are kept in the database for audit purposes but cannot be used for authentication. They remain visible in the token list with a "Revoked" status and timestamp. Revoked tokens cannot be reactivated. Create a new token if needed.

### 3.3. Application Configuration

**Note:** Exemplary configuration files for all supported providers can be found in the `docs/RestAPI/scripts/sample_configs` directory.

Initializes and validates the agent's core services, including the LLM provider and the MCP server connection. This is the first step required before creating sessions or submitting queries.

**Endpoint:** `POST /api/v1/configure`  
**Authentication:** Not required (global configuration)

**Request Body:**
    A JSON object containing the full configuration. The structure varies slightly by provider.

**Google, Anthropic, OpenAI:**
```json
{
  "provider": "Google",
  "model": "gemini-1.5-flash-latest",
  "credentials": {
    "apiKey": "YOUR_API_KEY"
  },
  "mcp_server": {
    "name": "my_mcp_server",
    "host": "localhost",
    "port": 8001,
    "path": "/mcp"
  }
}
```

**Friendli:**
```json
{
  "provider": "Friendli",
  "model": "meta-llama/Llama-3.3-70B-Instruct",
  "credentials": {
    "apiKey": "YOUR_FRIENDLI_API_KEY",
    "friendli_endpoint_url": "YOUR_FRIENDLI_ENDPOINT_URL" 
  },
  "mcp_server": { ... }
}
```

**Amazon Bedrock:**
```json
{
  "provider": "Amazon",
  "model": "amazon.titan-text-express-v1",
  "credentials": {
    "aws_access_key_id": "YOUR_AWS_ACCESS_KEY",
    "aws_secret_access_key": "YOUR_AWS_SECRET_KEY",
    "aws_region": "us-east-1"
  },
  "mcp_server": { ... }
}
```

**Ollama:**
```json
{
  "provider": "Ollama",
  "model": "llama2",
  "credentials": {
    "ollama_host": "http://localhost:11434"
  },
  "mcp_server": { ... }
}
```

**Success Response:**
```json
{
  "status": "success",
  "message": "MCP Server 'my_mcp_server' and LLM configured successfully."
}
```

**Error Responses:**
- `400 Bad Request` - Invalid configuration or authentication failed

### 3.4. Session Management

#### 📌 Important: User-Scoped Sessions

All sessions in the REST API are **automatically scoped to the authenticated user**. When you create a session or execute a query, the user identity is extracted from the authentication token (JWT or access token). You do not need to manually specify a user UUID. The system automatically:

- Associates sessions with your authenticated user
- Prevents access to other users' sessions (404 Not Found)
- Isolates all queries and task history by user

This means two different users calling the same endpoints with different authentication tokens will each see their own sessions.

#### 3.4.1. Create a New Session

Creates a new, isolated conversation session for the agent. A session stores context and history for subsequent queries.

**Endpoint:** `POST /api/v1/sessions`  
**Authentication:** Required (JWT or access token)

**Request Body:** None

**Success Response:**
```json
{
  "session_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef"
}
```

**Requirements:**
- User must be authenticated (JWT or access token)
- User must have a configured **default profile** (LLM + MCP Server)
- Profile must have both LLM and MCP server IDs configured

**Error Responses:**
- `401 Unauthorized` - Authentication required
- `400 Bad Request` - No default profile configured. Message: "No default profile configured for this user. Please configure a profile (LLM + MCP Server combination) in the Configuration panel first."
- `503 Service Unavailable` - Profile incomplete (missing LLM or MCP configuration)

#### 3.4.2. List Sessions

Get a filtered and sorted list of all user sessions.

**Endpoint:** `GET /api/v1/sessions`  
**Authentication:** Required (JWT or access token)

**Query Parameters:**
- `search` (string, optional): Search query to filter sessions
- `sort` (string, optional): Sort order - `recent`, `oldest`, `tokens`, `turns` (default: `recent`)
- `filter_status` (string, optional): Filter by status - `all`, `success`, `partial`, `failed` (default: `all`)
- `filter_model` (string, optional): Filter by model name (default: `all`)
- `limit` (integer, optional): Maximum results (default: 100)
- `offset` (integer, optional): Pagination offset (default: 0)

**Success Response:**
```json
{
  "sessions": [
    {
      "id": "session-uuid",
      "name": "Data Analysis Session",
      "created_at": "2025-11-19T10:00:00Z",
      "last_updated": "2025-11-19T10:15:00Z",
      "provider": "Google",
      "model": "gemini-1.5-flash",
      "input_tokens": 5000,
      "output_tokens": 3000,
      "turn_count": 3,
      "status": "success"
    }
  ],
  "total": 42
}
```

#### 3.4.3. Get Session Details

Get complete details for a specific session including timeline and RAG associations.

**Endpoint:** `GET /api/v1/sessions/{session_id}/details`  
**Authentication:** Required (JWT or access token)

**URL Parameters:**
- `session_id` (string, required): The session UUID

**Success Response:** Complete session data including `workflow_history`, `execution_trace`, and `rag_cases`

**Error Responses:**
- `404 Not Found` - Session not found
- `401 Unauthorized` - Authentication required

### 3.5. Query Execution

#### 3.5.1. Submit a Query

Submits a natural language query to a specific session. This initiates a background task for the agent to process the query. You can optionally specify a different profile for this query (profile override).

**Endpoint:** `POST /api/v1/sessions/{session_id}/query`  
**Authentication:** Required (JWT or access token)

**URL Parameters:**
- `session_id` (string, required): The session UUID

**Request Body:**
```json
{
  "prompt": "Your natural language query for the agent.",
  "profile_id": "profile-optional-override"
}
```

**Request Parameters:**
- `prompt` (string, required): The natural language query to submit
- `profile_id` (string, optional): Override the session's default profile with a specific profile ID. If omitted, uses the user's default profile. Use this to execute different queries with different LLM/MCP combinations within the same session.

**Success Response:**
```json
{
  "task_id": "task-9876-5432-1098-7654",
  "status_url": "/api/v1/tasks/task-9876-5432-1098-7654"
}
```

**Error Responses:**
- `404 Not Found` - Session not found
- `400 Bad Request` - Missing or invalid prompt, or profile_id does not exist
- `401 Unauthorized` - Authentication required

**Profile Override Examples:**

Basic query with default profile:
```bash
curl -X POST http://localhost:5050/api/v1/sessions/{session_id}/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the system version?"}'
```

Query with specific profile override:
```bash
curl -X POST http://localhost:5050/api/v1/sessions/{session_id}/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Tell me about the current date",
    "profile_id": "profile-1764006444002-z0hdduce9"
  }'
```

**Profile Visibility in UI:**
- Each message in the session displays the profile badge showing which profile was used
- Messages with the default profile show one badge (e.g., `@GOGET`)
- Messages with an override profile show the override profile badge (e.g., `@FRGOT`)
- The profile badge includes color-coding based on the profile's branding configuration

### 3.6. Task Management

#### 3.6.1. Get Task Status and Result

Polls for the status of a background task. This endpoint provides real-time progress updates through an event log and delivers the final result when the task is complete.

**Endpoint:** `GET /api/v1/tasks/{task_id}`  
**Authentication:** Required (JWT or access token)

**URL Parameters:**
- `task_id` (string, required): The task ID from "Submit a Query"

**Success Response:** See section **4. Data Models - The Task Object** for detailed structure.

**Error Responses:**
- `404 Not Found` - Task not found
- `401 Unauthorized` - Authentication required

#### 3.6.2. Cancel Task Execution

Requests cancellation of an actively running background task.

**Endpoint:** `POST /api/v1/tasks/{task_id}/cancel`  
**Authentication:** Required (JWT or access token)

**URL Parameters:**
- `task_id` (string, required): The task ID to cancel

**Request Body:** None

**Success Response:**
```json
{
  "status": "success",
  "message": "Cancellation request sent."
}
```

**Informational Response (Task Already Done):**
```json
{
  "status": "info",
  "message": "Task already completed."
}
```

**Error Responses:**
- `404 Not Found` - Task not found or already completed
- `401 Unauthorized` - Authentication required

### 3.7. RAG Collection Management

#### 3.7.1. Get All RAG Collections

Get all configured RAG collections with their active status.

**Endpoint:** `GET /api/v1/rag/collections`  
**Authentication:** Not required (public endpoint)

**Success Response:**
        ```json
        {
          "status": "success",
          "collections": [
            {
              "id": 1,
              "name": "Support Queries",
              "description": "Customer support query patterns",
              "mcp_server_id": "prod_server",
              "enabled": true,
              "is_active": true,
              "count": 150
            }
          ]
        }
        ```

#### 3.6.2. Create RAG Collection

Create a new RAG collection. All collections must be associated with an MCP server.

* **Endpoint**: `POST /api/v1/rag/collections`
* **Authentication**: Required (JWT or access token)
* **Method**: `POST`
* **Body**:
    ```json
    {
      "name": "Support Queries",
      "description": "Customer support query patterns",
      "mcp_server_id": "prod_server"
    }
    ```
* **Success Response**:
    * **Code**: `201 Created`
    * **Content**:
        ```json
        {
          "status": "success",
          "message": "Collection created successfully",
          "collection_id": 1,
          "mcp_server_id": "prod_server"
        }
        ```
* **Error Response**:
    * **Code**: `400 Bad Request` (if `mcp_server_id` is missing)

#### 3.6.3. Update RAG Collection

Update a RAG collection's metadata (name, description, MCP server association).

* **Endpoint**: `PUT /api/v1/rag/collections/{collection_id}`
* **Authentication**: Required (JWT or access token)
* **Method**: `PUT`
* **URL Parameters**:
    * `collection_id` (integer, required): The collection ID
* **Body**:
    ```json
    {
      "name": "Updated Name",
      "description": "Updated description",
      "mcp_server_id": "new_server"
    }
    ```
* **Success Response**:
    * **Code**: `200 OK`
* **Error Response**:
    * **Code**: `400 Bad Request` (if attempting to remove `mcp_server_id`)
    * **Code**: `404 Not Found` (if collection doesn't exist)

#### 3.6.4. Check Active Sessions for Collection

Check for active (non-archived) sessions that reference a specific collection in their workflow history. Use this endpoint **before deletion** to warn users about sessions that will be archived.

* **Endpoint**: `GET /api/v1/rag/collections/{collection_id}/check-sessions`
* **Authentication**: Required (JWT or access token)
* **Method**: `GET`
* **URL Parameters**:
    * `collection_id` (integer, required): The collection ID
* **Success Response**:
    * **Code**: `200 OK`
    * **Body**:
    ```json
    {
      "status": "success",
      "active_session_count": 3,
      "active_sessions": [
        {
          "session_id": "df8ebb81-5f32-4d4a-be5a-47a036bec54f",
          "session_name": "Sales Analysis Q1"
        },
        {
          "session_id": "a2b1c3d4-e5f6-7890-1234-567890abcdef",
          "session_name": "Product Query"
        }
      ]
    }
    ```
    * **Response Fields**:
        * `active_session_count` (integer) - Total number of active sessions using this collection
        * `active_sessions` (array) - List of up to 5 active sessions (for display purposes)
            * `session_id` (string) - Session UUID
            * `session_name` (string) - User-friendly session name
* **Use Case**:
    * Call this endpoint before showing a delete confirmation dialog
    * Display a dynamic warning like: "⚠️ Warning: 3 active sessions will be archived"
    * Show sample session names to help users understand impact
* **Error Response**:
    * **Code**: `401 Unauthorized` - Authentication required
    * **Code**: `500 Internal Server Error`

#### 3.6.5. Delete RAG Collection

Delete a RAG collection and its vector store. All sessions that reference this collection in their workflow history are automatically archived.

* **Endpoint**: `DELETE /api/v1/rag/collections/{collection_id}`
* **Authentication**: Required (JWT or access token)
* **Method**: `DELETE`
* **URL Parameters**:
    * `collection_id` (integer, required): The collection ID
* **Success Response**:
    * **Code**: `200 OK`
    * **Body**:
    ```json
    {
      "status": "success",
      "message": "Collection deleted successfully",
      "sessions_archived": 3,
      "archived_session_ids": [
        "df8ebb81-5f32-4d4a-be5a-47a036bec54f",
        "a2b1c3d4-e5f6-7890-1234-567890abcdef",
        "b3c2d1e0-f5a6-7891-2345-678901bcdefg"
      ]
    }
    ```
    * **Response Fields**:
        * `sessions_archived` (integer) - Number of sessions automatically archived
        * `archived_session_ids` (array) - List of archived session IDs
    * **Behavior**:
        * All sessions that used this collection for RAG retrieval are archived
        * Archived sessions are marked with `archived: true`, timestamp, and reason
        * Sessions remain accessible but hidden by default (can be shown via "Show Archived" toggle)
* **Error Response**:
    * **Code**: `400 Bad Request` - Cannot delete default collection or agent pack-managed collections
    * **Code**: `404 Not Found` - Collection not found

#### 3.6.6. Toggle RAG Collection

Enable or disable a RAG collection.

* **Endpoint**: `POST /api/v1/rag/collections/{collection_id}/toggle`
* **Authentication**: Required (JWT or access token)
* **Method**: `POST`
* **URL Parameters**:
    * `collection_id` (integer, required): The collection ID
* **Body**:
    ```json
    {
      "enabled": true
    }
    ```
* **Success Response**:
    * **Code**: `200 OK`
* **Error Response**:
    * **Code**: `400 Bad Request` (if enabling a collection without MCP server assignment)

#### 3.6.6. Refresh RAG Collection

Refresh the vector store for a specific collection (rebuilds from case files).

* **Endpoint**: `POST /api/v1/rag/collections/{collection_id}/refresh`
* **Authentication**: Required (JWT or access token)
* **Method**: `POST`
* **URL Parameters**:
    * `collection_id` (integer, required): The collection ID
* **Success Response**:
    * **Code**: `202 Accepted`
    * **Content**:
        ```json
        {
          "status": "success",
          "message": "Collection refresh started"
        }
        ```

#### 3.6.7. Submit Case Feedback

Submit user feedback (upvote/downvote) for a RAG case.

* **Endpoint**: `POST /api/v1/rag/cases/{case_id}/feedback`
* **Authentication**: Required (JWT or access token)
* **Method**: `POST`
* **URL Parameters**:
    * `case_id` (string, required): The case UUID
* **Body**:
    ```json
    {
      "feedback_score": 1
    }
    ```
    * `feedback_score`: `-1` (downvote), `0` (neutral), `1` (upvote)
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "message": "Feedback submitted successfully",
          "case_id": "f3a16261-82a9-5d30-a654-64af74f19fcd",
          "feedback_score": 1
        }
        ```
* **Error Response**:
    * **Code**: `400 Bad Request` (invalid feedback_score)
    * **Code**: `404 Not Found` (case not found)

### 3.8. RAG Template System

The RAG Template System enables automatic generation of RAG case studies through modular templates with LLM-assisted question generation.

#### 3.11.1. List Available Templates

Get all registered Planner Repository Constructors.

* **Endpoint**: `GET /v1/rag/templates`
* **Method**: `GET`
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "templates": [
            {
              "template_id": "sql_query_v1",
              "display_name": "SQL Query Template - Business Context",
              "description": "Two-phase strategy: Execute SQL and generate report",
              "version": "1.0.0",
              "status": "active"
            },
            {
              "template_id": "sql_query_doc_context_v1",
              "display_name": "SQL Query Template - Document Context",
              "description": "Three-phase strategy with document retrieval",
              "version": "1.0.0",
              "status": "active"
            }
          ]
        }
        ```

#### 3.6A.2. Get Template Plugin Info

Get detailed configuration for a specific template including manifest and UI field definitions.

* **Endpoint**: `GET /v1/rag/templates/{template_id}/plugin-info`
* **Method**: `GET`
* **URL Parameters**:
    * `template_id` (string, required): The template identifier (e.g., `sql_query_v1`)
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "template_id": "sql_query_v1",
          "plugin_info": {
            "name": "sql-query-basic",
            "version": "1.0.0",
            "display_name": "SQL Query Template - Business Context",
            "description": "Two-phase strategy...",
            "population_modes": {
              "manual": {
                "enabled": true,
                "input_variables": {
                  "database_name": {
                    "required": true,
                    "type": "string",
                    "description": "Target database name"
                  }
                }
              },
              "auto_generate": {
                "enabled": true,
                "input_variables": {
                  "context_topic": {
                    "required": true,
                    "type": "string",
                    "description": "Business context for generation"
                  },
                  "num_examples": {
                    "required": true,
                    "type": "integer",
                    "default": 5,
                    "min": 1,
                    "max": 1000,
                    "description": "Number of question/SQL pairs to generate"
                  }
                }
              }
            }
          }
        }
        ```

#### 3.6A.3. Generate Questions (LLM-Assisted)

Generate question/SQL pairs using LLM based on schema context and business requirements.

* **Endpoint**: `POST /v1/rag/generate-questions`
* **Method**: `POST`
* **Body**:
    ```json
    {
      "template_id": "sql_query_v1",
      "execution_context": "CREATE TABLE customers (id INT, name VARCHAR(100), email VARCHAR(100), status VARCHAR(20));\nCREATE TABLE orders (id INT, customer_id INT, total DECIMAL(10,2), created_at TIMESTAMP);",
      "subject": "Customer analytics and order reporting",
      "count": 10,
      "database_name": "sales_db"
    }
    ```
    * `template_id`: Template to use for generation
    * `execution_context`: Database schema information (from HELP TABLE, DESCRIBE, etc.)
    * `subject`: Business context topic for question generation
    * `count`: Number of question/SQL pairs to generate (1-1000)
    * `database_name`: Target database name
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "questions": [
            {
              "user_query": "Show all active customers",
              "sql_statement": "SELECT * FROM sales_db.customers WHERE status = 'active';"
            },
            {
              "user_query": "Count total orders by customer",
              "sql_statement": "SELECT customer_id, COUNT(*) as order_count FROM sales_db.orders GROUP BY customer_id;"
            }
          ],
          "input_tokens": 1234,
          "output_tokens": 567
        }
        ```
* **Error Response**:
    * **Code**: `400 Bad Request` (invalid parameters)
    * **Code**: `500 Internal Server Error` (LLM generation failed)

#### 3.6A.4. Generate Questions from Documents

Generate question/SQL pairs from uploaded technical documentation (PDF, TXT, DOC, DOCX). Uses the DocumentUploadHandler abstraction layer with provider-aware processing.

* **Endpoint**: `POST /v1/rag/generate-questions-from-documents`
* **Method**: `POST`
* **Authentication**: Required (JWT token in Authorization header)
* **Content-Type**: `multipart/form-data`
* **Form Data**:
    * `subject` (string, required): Technical domain or documentation topic (e.g., "database performance tuning")
    * `count` (integer, optional): Number of question/SQL pairs to generate (default: 5, max: 1000)
    * `database_name` (string, required): Target database name
    * `target_database` (string, optional): Database type (default: "Teradata")
    * `conversion_rules` (string, optional): SQL dialect conversion rules
    * `files` (file[], required): One or more document files (PDF, TXT, DOC, DOCX)
* **Example Request**:
    ```bash
    curl -X POST http://localhost:5050/api/v1/rag/generate-questions-from-documents \
      -H "Authorization: Bearer YOUR_JWT_TOKEN" \
      -F "subject=performance tuning" \
      -F "count=10" \
      -F "database_name=production_db" \
      -F "target_database=Teradata" \
      -F "files=@dba_guide.pdf" \
      -F "files=@optimization_tips.pdf"
    ```
* **Processing Details**:
    * Provider-aware document handling (Google native upload, Anthropic/Amazon native, others use text extraction)
    * Max file size determined by provider configuration (default: 20MB for Google, 10MB for Anthropic)
    * Documents processed using DocumentUploadHandler abstraction
    * Text extracted and passed to LLM for question generation
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "questions": [
            {
              "question": "How do I identify fragmented tables in Teradata?",
              "sql": "SELECT DatabaseName, TableName, CurrentPerm, PeakPerm FROM DBC.TableSize WHERE (CurrentPerm - PeakPerm) / NULLIFZERO(PeakPerm) > 0.20;"
            },
            {
              "question": "What is the query to find skewed tables?",
              "sql": "SELECT DatabaseName, TableName, Skew FROM DBC.TableSize WHERE Skew > 30;"
            }
          ],
          "count": 2,
          "documents_processed": 2,
          "total_document_size_mb": 15.2,
          "provider": "Google",
          "input_tokens": 2345,
          "output_tokens": 678
        }
        ```
* **Error Response**:
    * **Code**: `401 Unauthorized` (missing or invalid JWT token)
    * **Code**: `400 Bad Request` (validation errors)
        ```json
        {
          "status": "error",
          "message": "Subject is required"
        }
        ```
    * **Code**: `400 Bad Request` (file size exceeded)
        ```json
        {
          "status": "error",
          "message": "File performance_guide.pdf exceeds maximum size of 20MB (actual: 25.3MB)"
        }
        ```
    * **Code**: `503 Service Unavailable` (LLM not configured)
        ```json
        {
          "status": "error",
          "message": "LLM not configured for profile"
        }
        ```

**Notes**:
- Uses user's default profile configuration for LLM provider and model
- Document processing method determined by provider capabilities
- Supports multiple file uploads in single request
- Files are temporarily stored and cleaned up after processing

#### 3.6A.5. Populate Collection from Template

Populate a RAG collection with generated or manual examples using a template.

* **Endpoint**: `POST /v1/rag/collections/{collection_id}/populate`
* **Method**: `POST`
* **URL Parameters**:
    * `collection_id` (integer, required): The collection ID
* **Body**:
    ```json
    {
      "template_type": "sql_query",
      "examples": [
        {
          "user_query": "Show all active customers",
          "sql_statement": "SELECT * FROM sales_db.customers WHERE status = 'active';"
        },
        {
          "user_query": "Count total orders",
          "sql_statement": "SELECT COUNT(*) FROM sales_db.orders;"
        }
      ],
      "database_name": "sales_db",
      "mcp_tool_name": "base_readQuery"
    }
    ```
    * `template_type`: Currently only `"sql_query"` supported
    * `examples`: Array of question/SQL pairs
    * `database_name`: Optional database context
    * `mcp_tool_name`: Optional MCP tool override (default: `base_readQuery`)
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "message": "Successfully populated 2 cases",
          "results": {
            "total_examples": 2,
            "successful": 2,
            "failed": 0,
            "case_ids": [
              "abc123-def456-ghi789",
              "xyz789-uvw456-rst123"
            ],
            "errors": []
          }
        }
        ```
* **Error Response**:
    * **Code**: `400 Bad Request` (validation errors)
        ```json
        {
          "status": "error",
          "message": "Validation failed for some examples",
          "validation_issues": [
            {
              "example_index": 0,
              "field": "sql_statement",
              "issue": "SQL statement is empty or invalid"
            }
          ]
        }
        ```
    * **Code**: `404 Not Found` (collection not found)
    * **Code**: `500 Internal Server Error` (population failed)

### 3.9. MCP Server Management

#### 3.9.1. Get All MCP Servers

Get all configured MCP servers and the active server ID.

* **Endpoint**: `GET /v1/mcp/servers`
* **Method**: `GET`
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "servers": [
            {
              "id": "prod_server",
              "name": "Production Server",
              "host": "localhost",
              "port": 8001,
              "path": "/mcp"
            }
          ],
          "active_server_id": "prod_server"
        }
        ```

#### 3.9.2. Create MCP Server

Create a new MCP server configuration.

* **Endpoint**: `POST /v1/mcp/servers`
* **Method**: `POST`
* **Body**:
    ```json
    {
      "id": "dev_server",
      "name": "Development Server",
      "host": "localhost",
      "port": 8002,
      "path": "/mcp"
    }
    ```
* **Success Response**:
    * **Code**: `201 Created`
* **Error Response**:
    * **Code**: `400 Bad Request` (missing required fields)

#### 3.9.3. Update MCP Server

Update an existing MCP server configuration.

* **Endpoint**: `PUT /v1/mcp/servers/{server_id}`
* **Method**: `PUT`
* **URL Parameters**:
    * `server_id` (string, required): The server ID
* **Body**:
    ```json
    {
      "name": "Updated Name",
      "host": "newhost",
      "port": 8003
    }
    ```
* **Success Response**:
    * **Code**: `200 OK`
* **Error Response**:
    * **Code**: `404 Not Found`

#### 3.9.4. Delete MCP Server

Delete an MCP server configuration. Fails if any RAG collections are assigned to it.

* **Endpoint**: `DELETE /v1/mcp/servers/{server_id}`
* **Method**: `DELETE`
* **URL Parameters**:
    * `server_id` (string, required): The server ID
* **Success Response**:
    * **Code**: `200 OK`
* **Error Response**:
    * **Code**: `400 Bad Request` (if collections are assigned to this server)

#### 3.9.5. Activate MCP Server

Set an MCP server as the active server for the application.

* **Endpoint**: `POST /v1/mcp/servers/{server_id}/activate`
* **Method**: `POST`
* **URL Parameters**:
    * `server_id` (string, required): The server ID
* **Success Response**:
    * **Code**: `200 OK`
* **Error Response**:
    * **Code**: `404 Not Found`

### 3.10. Profile Management

The Profile Management API provides endpoints for creating, managing, and configuring agent profiles. Profiles define the combination of LLM providers, MCP servers, and execution behaviors that the agent uses to process queries.

**Key Concepts:**
- **Profile Types**: Different execution strategies (tool_enabled, llm_only, rag_focused, genie, conversation_with_tools)
- **Default Profile**: The profile automatically used for new sessions
- **Active for Consumption**: Profiles enabled for multi-profile coordination
- **Classification**: Automatic or manual categorization of MCP tools/prompts/resources
- **Genie Coordination**: Advanced multi-profile orchestration using LangChain agents
- **Session Archiving**: When profiles are deleted, all associated sessions are automatically archived with full traceability

#### Profile Types

| Type | Description | Use Case |
|------|-------------|----------|
| `tool_enabled` | Standard profile with MCP tools + LLM | Data queries, tool execution, standard workflows |
| `llm_only` | Pure conversational LLM without MCP | General chat, reasoning tasks without tool access |
| `rag_focused` | LLM + RAG retrieval only (no MCP tools) | Knowledge base queries, document search |
| `genie` | Multi-agent coordinator profile | Complex queries requiring multiple specialized profiles |
| `conversation_with_tools` | LangChain-based conversation agent | Conversational workflows with tool use |

#### 3.10.1. List All Profiles

Retrieve all profile configurations for the authenticated user.

**Endpoint:** `GET /api/v1/profiles`
**Authentication:** Required (JWT or access token)
**Parameters:** None

**Success Response:**
```json
{
  "status": "success",
  "profiles": [
    {
      "id": "profile-550e8400-e29b",
      "name": "Teradata SQL Agent",
      "tag": "TDAT",
      "description": "Teradata database query and analysis",
      "profile_type": "tool_enabled",
      "color": "#FF6B35",
      "colorSecondary": "#F7931E",
      "llmConfigurationId": "llm-config-123",
      "mcpServerId": "mcp-teradata-456",
      "providerName": "Google",
      "classification_mode": "llm",
      "is_default": true,
      "active_for_consumption": true,
      "created_at": "2026-01-13T10:00:00Z",
      "updated_at": "2026-01-13T12:00:00Z"
    },
    {
      "id": "profile-genie-001",
      "name": "Genie Coordinator",
      "tag": "GENIE",
      "description": "Multi-agent coordination profile",
      "profile_type": "genie",
      "color": "#F59E0B",
      "colorSecondary": "#FCD34D",
      "llmConfigurationId": "llm-config-789",
      "genieConfig": {
        "slaveProfiles": ["profile-550e8400-e29b", "profile-rag-002"]  // Field name preserved for API compatibility
      },
      "is_default": false,
      "active_for_consumption": false,
      "created_at": "2026-01-13T11:00:00Z"
    }
  ]
}
```

**Error Responses:**
- `401 Unauthorized` - Authentication required
- `500 Internal Server Error` - Server error retrieving profiles

---

#### 3.10.2. Get Profile by ID

Retrieve detailed information about a specific profile.

**Endpoint:** `GET /api/v1/profiles/{profile_id}`
**Authentication:** Required (JWT or access token)
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Success Response:**
```json
{
  "status": "success",
  "profile": {
    "id": "profile-550e8400-e29b",
    "name": "Teradata SQL Agent",
    "tag": "TDAT",
    "description": "Teradata database query and analysis",
    "profile_type": "tool_enabled",
    "color": "#FF6B35",
    "colorSecondary": "#F7931E",
    "llmConfigurationId": "llm-config-123",
    "mcpServerId": "mcp-teradata-456",
    "providerName": "Google",
    "classification_mode": "llm",
    "classificationPromptId": "custom-classification-prompt",
    "ragCollectionIds": ["collection-001", "collection-002"],
    "is_default": true,
    "active_for_consumption": true,
    "useMcpTools": true,
    "created_at": "2026-01-13T10:00:00Z",
    "updated_at": "2026-01-13T12:00:00Z"
  }
}
```

---

#### 3.10.3. Create Profile

Create a new profile configuration.

**Endpoint:** `POST /api/v1/profiles`
**Authentication:** Required (JWT or access token)
**Content-Type:** `application/json`

**Request Body:**
```json
{
  "name": "My SQL Agent",
  "tag": "MYSQL",
  "description": "MySQL database queries",
  "profile_type": "tool_enabled",
  "color": "#4285F4",
  "colorSecondary": "#34A853",
  "llmConfigurationId": "llm-config-123",
  "mcpServerId": "mcp-mysql-456",
  "providerName": "Anthropic",
  "classification_mode": "filter",
  "ragCollectionIds": [],
  "useMcpTools": true
}
```

**Required Fields:**
- `name` (string) - Profile display name
- `tag` (string) - Unique tag for @TAG syntax (3-20 uppercase alphanumeric characters)
- `profile_type` (string) - One of: `tool_enabled`, `llm_only`, `rag_focused`, `genie`, `conversation_with_tools`
- `llmConfigurationId` (string) - Reference to LLM configuration

**Optional Fields:**
- `description` (string) - Profile description
- `color` (string) - Primary color (hex code)
- `colorSecondary` (string) - Secondary color (hex code)
- `mcpServerId` (string) - MCP server ID (required for tool_enabled profiles)
- `providerName` (string) - LLM provider name override
- `classification_mode` (string) - `filter` or `llm` (for tool_enabled profiles)
- `classificationPromptId` (string) - Custom classification prompt
- `ragCollectionIds` (array) - RAG collection IDs
- `useMcpTools` (boolean) - Enable MCP tools (for llm_only profiles with conversation)
- `genieConfig` (object) - Genie-specific configuration (for genie profiles)

**Genie Profile Configuration:**
```json
{
  "name": "Genie Coordinator",
  "tag": "GENIE",
  "profile_type": "genie",
  "llmConfigurationId": "llm-config-789",
  "genieConfig": {
    "slaveProfiles": [  // Field name preserved for API compatibility
      "profile-teradata-001",
      "profile-postgres-002",
      "profile-rag-003"
    ]
  }
}
```

**Success Response:**
```json
{
  "status": "success",
  "message": "Profile created successfully",
  "profile": {
    "id": "profile-new-123",
    "name": "My SQL Agent",
    "tag": "MYSQL",
    ...
  }
}
```

**Error Responses:**
- `400 Bad Request` - Invalid request body or duplicate tag
- `401 Unauthorized` - Authentication required
- `500 Internal Server Error` - Server error creating profile

---

#### 3.10.4. Update Profile

Update an existing profile configuration.

**Endpoint:** `PUT /api/v1/profiles/{profile_id}`
**Authentication:** Required (JWT or access token)
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Request Body:** Same structure as Create Profile (all fields optional except those being updated)

**Success Response:**
```json
{
  "status": "success",
  "message": "Profile updated successfully",
  "profile": {
    "id": "profile-550e8400-e29b",
    "name": "Updated Profile Name",
    ...
  }
}
```

---

#### 3.10.5. Check Active Sessions for Profile

Check for active (non-archived) sessions that use a specific profile. Use this endpoint **before deletion** to warn users about sessions that will be archived.

**Endpoint:** `GET /api/v1/profiles/{profile_id}/check-sessions`
**Authentication:** Required (JWT or access token)
**Method:** `GET`
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Success Response:**
```json
{
  "status": "success",
  "active_session_count": 5,
  "active_sessions": [
    {
      "session_id": "df8ebb81-5f32-4d4a-be5a-47a036bec54f",
      "session_name": "Database Analysis"
    },
    {
      "session_id": "a2b1c3d4-e5f6-7890-1234-567890abcdef",
      "session_name": "Customer Insights"
    }
  ]
}
```

**Response Fields:**
- `active_session_count` (integer) - Total number of active sessions using this profile
- `active_sessions` (array) - List of up to 5 active sessions (for display purposes)
    - `session_id` (string) - Session UUID
    - `session_name` (string) - User-friendly session name

**Use Case:**
- Call this endpoint before showing a delete confirmation dialog
- Display a dynamic warning like: "⚠️ Warning: 5 active sessions will be archived"
- Show sample session names to help users understand impact
- Both regular sessions and Genie child sessions are included in the count

**Error Responses:**
- `401 Unauthorized` - Authentication required
- `500 Internal Server Error`

**Example:**
```bash
# Check active sessions before deleting profile
curl -X GET http://localhost:5050/api/v1/profiles/profile-123/check-sessions \
  -H "Authorization: Bearer $TOKEN"
```

---

#### 3.10.6. Delete Profile

Delete a profile configuration. Cannot delete the default profile.

**Endpoint:** `DELETE /api/v1/profiles/{profile_id}`
**Authentication:** Required (JWT or access token)
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Success Response:**
```json
{
  "status": "success",
  "message": "Profile deleted successfully",
  "sessions_archived": 5,
  "archived_session_ids": [
    "df8ebb81-5f32-4d4a-be5a-47a036bec54f",
    "a2b1c3d4-e5f6-7890-1234-567890abcdef",
    "..."
  ],
  "genie_children_archived": 2
}
```

**Response Fields:**
- `sessions_archived` (integer) - Number of sessions automatically archived
- `archived_session_ids` (array) - List of archived session IDs
- `genie_children_archived` (integer) - Number of Genie child sessions archived

**Behavior:**
- All sessions using this profile are automatically archived (marked as `archived: true` with reason and timestamp)
- Archived sessions remain accessible but are hidden by default in the UI
- Users can view archived sessions by enabling "Show Archived" toggle in Sessions panel
- Genie child sessions linked to this profile are also archived and tracked in `genie_session_links` table

**Error Responses:**
- `400 Bad Request` - Cannot delete default profile while other profiles exist (safeguard)
- `404 Not Found` - Profile not found
- `401 Unauthorized` - Authentication required

---

#### 3.10.7. Get Default Profile

Retrieve the current default profile information for the authenticated user. This is useful for checking which profile will be used for new sessions or verifying before deletion operations.

**Endpoint:** `GET /api/v1/profiles/default`
**Authentication:** Required (JWT or access token)
**Parameters:** None

**Success Response:**
```json
{
  "status": "success",
  "profile": {
    "id": "profile-550e8400-e29b",
    "name": "Teradata SQL Agent",
    "tag": "TDAT",
    "profile_type": "tool_enabled",
    "llmConfigurationId": "llm-config-123",
    "mcpServerId": "mcp-server-456",
    "description": "Teradata database query and analysis"
  }
}
```

**Use Cases:**
- Check which profile is currently set as default before attempting deletion
- Verify default profile configuration in automation scripts
- Display current default profile in UI/dashboards

**Error Responses:**
- `404 Not Found` - No default profile configured
- `401 Unauthorized` - Authentication required

---

#### 3.10.7. Set Default Profile

Mark a profile as the default profile for the user account. New sessions will automatically use this profile.

**Endpoint:** `POST /api/v1/profiles/{profile_id}/set_default`
**Authentication:** Required (JWT or access token)
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Success Response:**
```json
{
  "status": "success",
  "message": "Default profile set successfully",
  "profile_id": "profile-550e8400-e29b"
}
```

---

#### 3.10.8. Activate Profile

Activate a profile, switching the runtime context to use its configuration. This loads the profile's LLM settings, MCP servers, and classification results. Requires all profile tests to pass.

**Endpoint:** `POST /api/v1/profiles/{profile_id}/activate`
**Authentication:** Required (JWT or access token)
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Success Response:**
```json
{
  "status": "success",
  "message": "Profile activated successfully",
  "profile_id": "profile-550e8400-e29b",
  "details": {
    "llm_loaded": true,
    "mcp_loaded": true,
    "classification_loaded": true
  }
}
```

**Error Responses:**
- `400 Bad Request` - Profile tests not passed
- `503 Service Unavailable` - Profile activation failed

---

#### 3.10.9. Test Profile

Test a profile's configuration (LLM connectivity, MCP connectivity).

**Endpoint:** `POST /api/v1/profiles/{profile_id}/test`
**Authentication:** Required (JWT or access token)
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Success Response:**
```json
{
  "status": "success",
  "test_results": {
    "llm_test": {
      "passed": true,
      "message": "LLM connection successful",
      "latency_ms": 245
    },
    "mcp_test": {
      "passed": true,
      "message": "MCP server connected successfully",
      "tools_count": 12,
      "prompts_count": 3,
      "resources_count": 5
    }
  }
}
```

---

#### 3.10.9. Get Profile Resources

Get filtered tools, prompts, and resources for a specific profile. Used for real-time resource panel updates when @TAG is typed.

**Endpoint:** `GET /api/v1/profiles/{profile_id}/resources`
**Authentication:** Required (JWT or access token)
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Success Response for tool_enabled profiles:**
```json
{
  "status": "success",
  "tools": {
    "base_readQuery": {
      "name": "base_readQuery",
      "description": "Execute SELECT queries on the database",
      "inputSchema": {
        "type": "object",
        "properties": {
          "sql": {
            "type": "string",
            "description": "The SQL query to execute"
          }
        },
        "required": ["sql"]
      }
    }
  },
  "prompts": {
    "system_prompt": {
      "name": "system_prompt",
      "description": "System initialization prompt"
    }
  },
  "profile_type": "tool_enabled",
  "profile_tag": "TDAT"
}
```

**Success Response for genie profiles:**
```json
{
  "status": "success",
  "tools": {},
  "prompts": {},
  "profile_type": "genie",
  "profile_tag": "GENIE",
  "slave_profiles": [  // Field name preserved for API compatibility
    {
      "id": "profile-teradata-001",
      "name": "Teradata Agent",
      "tag": "TDAT"
    },
    {
      "id": "profile-rag-002",
      "name": "RAG Knowledge Base",
      "tag": "RAG"
    }
  ]
}
```

**Note:** Genie profiles don't have direct tools/prompts - they coordinate child profiles. The response includes information about coordinated profiles instead.

---

#### 3.10.10. Get Profile Classification

Get the classification results for a specific profile. Returns the cached classification structure (tools, prompts, resources).

**Endpoint:** `GET /api/v1/profiles/{profile_id}/classification`
**Authentication:** Required (JWT or access token)
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Success Response:**
```json
{
  "status": "success",
  "profile_id": "profile-550e8400-e29b",
  "classification_mode": "llm",
  "classification_results": {
    "tools": {
      "query_execution": ["base_readQuery", "base_writeQuery"],
      "schema_inspection": ["base_listDatabases", "base_listTables"],
      "data_operations": ["base_createTable", "base_dropTable"]
    },
    "prompts": {
      "system": ["system_prompt"],
      "examples": ["query_examples"]
    },
    "resources": {
      "documentation": ["teradata_docs", "sql_reference"]
    }
  }
}
```

---

#### 3.10.11. Reclassify Profile

Force reclassification of MCP resources for a specific profile. Clears cached results and re-runs classification using the profile's LLM and mode.

**Endpoint:** `POST /api/v1/profiles/{profile_id}/reclassify`
**Authentication:** Required (JWT or access token)
**Path Parameters:**
- `profile_id` (string, required) - Profile identifier

**Request Body (Optional):**
```json
{
  "classification_mode": "llm"
}
```

**Success Response:**
```json
{
  "status": "success",
  "message": "Profile reclassified successfully",
  "profile_id": "profile-550e8400-e29b",
  "classification_results": {
    "tools": { ... },
    "prompts": { ... },
    "resources": { ... }
  }
}
```

---

#### 3.10.12. Set Active Profiles for Consumption

Set the list of profiles active for consumption (multi-profile coordination). Updates APP_STATE with enabled/disabled profile lists.

**Endpoint:** `POST /api/v1/profiles/set_active_for_consumption`
**Authentication:** Required (JWT or access token)
**Content-Type:** `application/json`

**Request Body:**
```json
{
  "profile_ids": [
    "profile-teradata-001",
    "profile-postgres-002",
    "profile-rag-003"
  ]
}
```

**Success Response:**
```json
{
  "status": "success",
  "message": "Active profiles updated successfully",
  "active_profile_ids": [
    "profile-teradata-001",
    "profile-postgres-002",
    "profile-rag-003"
  ]
}
```

---

### Profile Override in Query Execution

You can override the default profile for individual queries using the `profile_id` parameter in the query submission endpoint:

```bash
# Create session (uses default profile)
SESSION_ID="your-session-id"

# Submit query with profile override
curl -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What databases are available?",
    "profile_id": "profile-teradata-001"
  }'
```

**Profile Override Behavior:**
- Temporary override for single query only
- Subsequent queries return to default profile
- Useful for multi-profile workflows
- Genie profiles automatically coordinate multiple child profiles

---

### Genie Profile Coordination

Genie profiles provide multi-agent coordination capabilities using LangChain ReAct agents:

**Key Features:**
- **Intelligent Routing**: Automatically routes queries to appropriate child profiles
- **Multi-Profile Consultation**: Can invoke multiple profiles for comprehensive answers
- **Synthesis**: Combines results from multiple profiles into coherent response
- **Session Tracking**: Creates child sessions linked to parent session
- **Visual Hierarchy**: Parent/child session relationships visible in UI

**Genie Profile Structure:**
```json
{
  "profile_type": "genie",
  "genieConfig": {
    "slaveProfiles": [  // Field name preserved for API compatibility
      "profile-teradata-001",    // SQL queries
      "profile-rag-002",          // Knowledge base
      "profile-analytics-003"     // Analytics tools
    ]
  }
}
```

**Genie Execution Flow:**
1. User submits query to Genie profile
2. Genie coordinator analyzes query intent
3. Routes to appropriate child profile(s)
4. Collects responses from invoked profiles
5. Synthesizes final response
6. Returns comprehensive answer to user

**Event Notifications:**
During Genie execution, the following SSE events are emitted:
- `genie_coordination_start` - Coordination begins
- `genie_llm_step` - LLM processing step
- `genie_routing_decision` - Profiles selected
- `genie_slave_invoked` - Child profile called (event name preserved for API compatibility)
- `genie_slave_completed` - Child response received (event name preserved for API compatibility)
- `genie_synthesis_start` - Response synthesis begins
- `genie_coordination_complete` - Coordination complete

**Database Schema:**
Genie coordination creates session links tracked in `genie_session_links` table:
- `parent_session_id` - Parent Genie session
- `slave_session_id` - Child profile session (column name preserved for API compatibility)
- `slave_profile_id` - Profile used for child (column name preserved for API compatibility)
- `slave_profile_tag` - Profile tag (e.g., @TDAT)
- `execution_order` - Order of invocation

---
### 3.11. Session Analytics and Management

#### 3.11.1. Get Session Analytics

Get comprehensive analytics across all sessions for the execution dashboard.

* **Endpoint**: `GET /v1/sessions/analytics`
* **Method**: `GET`
* **Authentication**: Required (JWT or access token)
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "total_sessions": 42,
          "total_tokens": {
            "input": 125000,
            "output": 85000,
            "total": 210000
          },
          "success_rate": 87.5,
          "estimated_cost": 2.10,
          "model_distribution": {
            "gemini-1.5-flash": 60.0,
            "gpt-4": 40.0
          },
          "top_champions": [
            {
              "query": "What databases are available?",
              "tokens": 320,
              "case_id": "abc-123"
            }
          ],
          "velocity_data": [
            {"hour": "2025-11-19 10:00", "count": 5}
          ]
        }
        ```

#### 3.11.2. Get Sessions List

Get a filtered and sorted list of all sessions.

* **Endpoint**: `GET /v1/sessions`
* **Method**: `GET`
* **Authentication**: Required (JWT or access token)
* **Query Parameters**:
    * `search` (string, optional): Search query to filter sessions
    * `sort` (string, optional): Sort order - `recent`, `oldest`, `tokens`, `turns` (default: `recent`)
    * `filter_status` (string, optional): Filter by status - `all`, `success`, `partial`, `failed` (default: `all`)
    * `filter_model` (string, optional): Filter by model name (default: `all`)
    * `limit` (integer, optional): Maximum number of results (default: 100)
    * `offset` (integer, optional): Pagination offset (default: 0)
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "sessions": [
            {
              "id": "session-uuid",
              "name": "Data Analysis Session",
              "created_at": "2025-11-19T10:00:00Z",
              "last_updated": "2025-11-19T10:15:00Z",
              "provider": "Google",
              "model": "gemini-1.5-flash",
              "input_tokens": 5000,
              "output_tokens": 3000,
              "turn_count": 3,
              "status": "success"
            }
          ],
          "total": 42
        }
        ```

#### 3.11.3. Get Session Details

Get complete details for a specific session including timeline and RAG associations.

* **Endpoint**: `GET /v1/sessions/{session_id}/details`
* **Method**: `GET`
* **Authentication**: Required (JWT or access token)
* **URL Parameters**:
    * `session_id` (string, required): The session UUID
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**: Complete session data including `workflow_history`, `execution_trace`, and `rag_cases`
* **Error Response**:
    * **Code**: `404 Not Found`

---


### 3.12. System Prompts Management

The System Prompts API provides endpoints for managing profile-specific prompt mappings. This allows fine-grained control over which prompt versions are used for different functional areas (master system prompts, workflow classification, error recovery, data operations, visualization) on a per-profile basis.

**Key Concepts:**
- **Categories**: Functional areas like `master_system`, `workflow_classification`, `error_recovery`, `data_operations`, `visualization`
- **Subcategories**: Specific providers (for master_system) or functional roles (for other categories)
- **3-Level Fallback**: Profile-specific → System default → Configuration file defaults
- **Active Versions**: Mappings always use the active version of the mapped prompt

#### 3.12.1. Get Available Prompts

Retrieve all available prompts organized by category and subcategory for dropdown population in UI.

* **Endpoint**: `GET /api/v1/system-prompts/available`
* **Method**: `GET`
* **Authentication**: Required (JWT or access token)
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "success": true,
          "categories": {
            "master_system": {
              "Google": [
                {
                  "name": "GOOGLE_MASTER_SYSTEM_PROMPT",
                  "display_name": "Google Master System Prompt",
                  "version": 3
                }
              ],
              "Anthropic": [
                {
                  "name": "MASTER_SYSTEM_PROMPT",
                  "display_name": "Master System Prompt",
                  "version": 2
                }
              ]
            },
            "workflow_classification": {
              "task_classification": [
                {
                  "name": "TASK_CLASSIFICATION_PROMPT",
                  "display_name": "Task Classification",
                  "version": 1
                }
              ]
            },
            "error_recovery": {
              "error_recovery": [...],
              "tactical_self_correction": [...]
            },
            "data_operations": {
              "sql_consolidation": [...]
            },
            "visualization": {
              "charting_instructions": [...],
              "g2plot_guidelines": [...]
            }
          },
          "total_prompts": 15
        }
        ```
* **Error Response**:
    * **Code**: `500 Internal Server Error`

#### 3.12.2. Get Profile Prompt Mappings

Retrieve all prompt mappings for a specific profile.

* **Endpoint**: `GET /api/v1/system-prompts/profiles/{profile_id}/mappings`
* **Method**: `GET`
* **Authentication**: Required (JWT or access token)
* **URL Parameters**:
    * `profile_id` (string, required): The profile UUID
* **Authorization**: Users can only view their own profiles; admins can view all profiles
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "success": true,
          "profile_id": "profile-123-abc",
          "mappings": {
            "master_system": {
              "Google": "GOOGLE_MASTER_SYSTEM_PROMPT",
              "Anthropic": "MASTER_SYSTEM_PROMPT"
            },
            "workflow_classification": {
              "task_classification": "TASK_CLASSIFICATION_PROMPT"
            },
            "error_recovery": {
              "error_recovery": "ERROR_RECOVERY_PROMPT"
            },
            "data_operations": {},
            "visualization": {}
          }
        }
        ```
* **Error Responses**:
    * **Code**: `403 Forbidden` - User does not have permission to view this profile
    * **Code**: `500 Internal Server Error`

**Note:** Empty subcategories (`{}`) indicate the profile uses system defaults for those areas.

#### 3.12.3. Set Profile Prompt Mappings

Set or update prompt mappings for a profile. Supports single or bulk operations.

* **Endpoint**: `POST /api/v1/system-prompts/profiles/{profile_id}/mappings`
* **Method**: `POST`
* **Authentication**: Required (JWT or access token)
* **URL Parameters**:
    * `profile_id` (string, required): The profile UUID
* **Authorization**: Users can only modify their own profiles; admins can modify all profiles
* **Request Body (Single Mapping)**:
    ```json
    {
      "category": "master_system",
      "subcategory": "Google",
      "prompt_name": "GOOGLE_MASTER_SYSTEM_PROMPT"
    }
    ```
* **Request Body (Bulk Mappings)**:
    ```json
    {
      "mappings": [
        {
          "category": "master_system",
          "subcategory": "Google",
          "prompt_name": "GOOGLE_MASTER_SYSTEM_PROMPT"
        },
        {
          "category": "workflow_classification",
          "subcategory": "task_classification",
          "prompt_name": "TASK_CLASSIFICATION_PROMPT"
        }
      ]
    }
    ```
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "success": true,
          "message": "Set 2/2 mapping(s)",
          "results": [
            {
              "status": "success",
              "category": "master_system",
              "subcategory": "Google"
            },
            {
              "status": "success",
              "category": "workflow_classification",
              "subcategory": "task_classification"
            }
          ]
        }
        ```
* **Error Responses**:
    * **Code**: `400 Bad Request` - Missing required fields
    * **Code**: `403 Forbidden` - User does not have permission to modify this profile
    * **Code**: `500 Internal Server Error`

#### 3.12.4. Delete Profile Prompt Mappings

Delete specific prompt mappings or all mappings for a profile (reset to system defaults).

* **Endpoint**: `DELETE /api/v1/system-prompts/profiles/{profile_id}/mappings`
* **Method**: `DELETE`
* **Authentication**: Required (JWT or access token)
* **URL Parameters**:
    * `profile_id` (string, required): The profile UUID
* **Query Parameters** (optional - omit both to delete all mappings):
    * `category` (string, optional): Category to reset
    * `subcategory` (string, optional): Subcategory to reset
* **Authorization**: Users can only modify their own profiles; admins can modify all profiles
* **Success Response (Specific Mapping)**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "success": true,
          "message": "Deleted mapping for master_system/Google"
        }
        ```
* **Success Response (All Mappings)**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "success": true,
          "message": "Deleted all 5 mapping(s) for profile"
        }
        ```
* **Error Responses**:
    * **Code**: `403 Forbidden` - User does not have permission to modify this profile
    * **Code**: `500 Internal Server Error`

**Examples:**

```bash
# Get available prompts
curl -X GET http://localhost:5050/api/v1/system-prompts/available \
  -H "Authorization: Bearer $TOKEN"

# Get profile mappings
curl -X GET http://localhost:5050/api/v1/system-prompts/profiles/profile-123/mappings \
  -H "Authorization: Bearer $TOKEN"

# Set a single mapping
curl -X POST http://localhost:5050/api/v1/system-prompts/profiles/profile-123/mappings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "category": "master_system",
    "subcategory": "Google",
    "prompt_name": "GOOGLE_MASTER_SYSTEM_PROMPT"
  }'

# Set multiple mappings at once
curl -X POST http://localhost:5050/api/v1/system-prompts/profiles/profile-123/mappings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mappings": [
      {"category": "master_system", "subcategory": "Google", "prompt_name": "GOOGLE_MASTER_SYSTEM_PROMPT"},
      {"category": "workflow_classification", "subcategory": "task_classification", "prompt_name": "TASK_CLASSIFICATION_PROMPT"}
    ]
  }'

# Delete specific mapping (reset to system default)
curl -X DELETE "http://localhost:5050/api/v1/system-prompts/profiles/profile-123/mappings?category=master_system&subcategory=Google" \
  -H "Authorization: Bearer $TOKEN"

# Delete all mappings for profile
curl -X DELETE http://localhost:5050/api/v1/system-prompts/profiles/profile-123/mappings \
  -H "Authorization: Bearer $TOKEN"
```

---

### 3.13. Document Upload

Upload documents and images to include as context in chat conversations. The platform supports native multimodal processing for providers that support it (Google Gemini, Anthropic Claude, OpenAI GPT-4o, Azure OpenAI, AWS Bedrock Claude) and automatic text extraction fallback for all others.

#### 3.13.1. Get Upload Capabilities

Returns the document upload capabilities for the current user's active profile, including supported formats, size limits, and provider-specific features.

* **Endpoint**: `GET /api/v1/chat/upload-capabilities`
* **Method**: `GET`
* **Authentication**: Required (JWT or access token)
* **Query Parameters**:
    * `session_id` (string, optional): Session UUID to check provider-specific capabilities
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "capabilities": {
            "enabled": true,
            "provider": "Google",
            "model": "gemini-2.5-flash",
            "supported_formats": [".doc", ".docx", ".gif", ".jpeg", ".jpg", ".md", ".pdf", ".png", ".txt", ".webp"],
            "max_file_size_mb": 50,
            "max_files_per_message": 5,
            "text_extraction_formats": [".doc", ".docx", ".md", ".pdf", ".txt"],
            "image_formats": [".gif", ".jpeg", ".jpg", ".png", ".webp"]
          }
        }
        ```

**Example:**
```bash
curl -X GET "http://localhost:5050/api/v1/chat/upload-capabilities?session_id=$SESSION_ID" \
  -H "Authorization: Bearer $TOKEN"
```

#### 3.13.2. Upload Files

Upload one or more files to attach to a chat message. Files are stored server-side and text content is extracted for providers that don't support native document processing. Images are preserved for native multimodal delivery to vision-capable models.

* **Endpoint**: `POST /api/v1/chat/upload`
* **Method**: `POST`
* **Authentication**: Required (JWT or access token)
* **Content-Type**: `multipart/form-data`
* **Form Parameters**:
    * `session_id` (string, required): The session UUID to associate files with
    * `files` (file, required): One or more files to upload (use multiple `files` fields for multiple files)
* **Constraints**:
    * Maximum 5 files per upload
    * Maximum 50 MB per file
    * Supported formats: `.pdf`, `.txt`, `.docx`, `.doc`, `.md`, `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "files": [
            {
              "file_id": "540327ad-1234-5678-abcd-ef0123456789",
              "original_filename": "report.pdf",
              "content_type": "application/pdf",
              "file_size": 45230,
              "extracted_text_preview": "Quarterly Financial Summary...",
              "extracted_text_length": 2450,
              "is_image": false
            },
            {
              "file_id": "6de6b487-abcd-1234-5678-ef0123456789",
              "original_filename": "chart.png",
              "content_type": "image/png",
              "file_size": 4580,
              "extracted_text_preview": "[Image file: chart.png - visual content not available in text mode]",
              "extracted_text_length": 67,
              "is_image": true
            }
          ]
        }
        ```
* **Error Responses**:
    * **Code**: `400 Bad Request` - Missing session_id, no files, unsupported format, file too large, or empty file
    * **Code**: `401 Unauthorized` - Authentication required
    * **Code**: `404 Not Found` - Session not found
    * **Code**: `500 Internal Server Error`

**Example:**
```bash
curl -X POST http://localhost:5050/api/v1/chat/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "session_id=$SESSION_ID" \
  -F "files=@report.pdf" \
  -F "files=@chart.png"
```

#### 3.13.3. Delete Uploaded File

Remove a pending file upload before the message is sent. This deletes the file from server storage and removes it from the session manifest.

* **Endpoint**: `DELETE /api/v1/chat/upload/{file_id}`
* **Method**: `DELETE`
* **Authentication**: Required (JWT or access token)
* **URL Parameters**:
    * `file_id` (string, required): The file UUID returned from the upload endpoint
* **Query Parameters**:
    * `session_id` (string, required): The session UUID the file belongs to
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "message": "File deleted"
        }
        ```
* **Error Responses**:
    * **Code**: `400 Bad Request` - Missing session_id
    * **Code**: `401 Unauthorized` - Authentication required
    * **Code**: `404 Not Found` - File not found
    * **Code**: `500 Internal Server Error`

**Example:**
```bash
curl -X DELETE "http://localhost:5050/api/v1/chat/upload/$FILE_ID?session_id=$SESSION_ID" \
  -H "Authorization: Bearer $TOKEN"
```

#### 3.13.4. Submit Query with Attachments

When submitting a query via the SSE streaming endpoint, include the file references from the upload response in the `attachments` field. The platform automatically determines whether to use native multimodal delivery or text extraction based on the active provider's capabilities.

**Request Body (SSE endpoint `/ask_stream`):**
```json
{
  "message": "Analyze this quarterly report and describe the chart",
  "session_id": "session-uuid",
  "attachments": [
    {
      "file_id": "540327ad-1234-5678-abcd-ef0123456789",
      "filename": "report.pdf",
      "content_type": "application/pdf",
      "is_image": false,
      "file_size": 45230
    },
    {
      "file_id": "6de6b487-abcd-1234-5678-ef0123456789",
      "filename": "chart.png",
      "content_type": "image/png",
      "is_image": true,
      "file_size": 4580
    }
  ]
}
```

**Provider-Specific Processing:**

| Provider | Images | PDFs | Other Documents |
|----------|--------|------|-----------------|
| Google Gemini | Native multimodal | Native multimodal | Text extraction |
| Anthropic Claude | Native base64 | Native base64 | Text extraction |
| OpenAI GPT-4o | Native image_url | Text extraction | Text extraction |
| Azure OpenAI (GPT-4o) | Native image_url | Text extraction | Text extraction |
| AWS Bedrock (Claude) | Native multimodal | Native multimodal | Text extraction |
| AWS Bedrock (Nova, etc.) | Text extraction | Text extraction | Text extraction |
| Friendli.AI | Text extraction | Text extraction | Text extraction |
| Ollama | Text extraction | Text extraction | Text extraction |

**Complete Upload + Query Workflow:**
```bash
# 1. Check capabilities
curl -s -X GET "http://localhost:5050/api/v1/chat/upload-capabilities?session_id=$SESSION_ID" \
  -H "Authorization: Bearer $TOKEN" | jq '.capabilities'

# 2. Upload files
UPLOAD_RESULT=$(curl -s -X POST http://localhost:5050/api/v1/chat/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "session_id=$SESSION_ID" \
  -F "files=@report.pdf" \
  -F "files=@chart.png")

echo "$UPLOAD_RESULT" | jq '.files[].file_id'

# 3. Extract file references for the query
FILE1_ID=$(echo "$UPLOAD_RESULT" | jq -r '.files[0].file_id')
FILE2_ID=$(echo "$UPLOAD_RESULT" | jq -r '.files[1].file_id')

# 4. Submit query with attachments via REST API
TASK_RESPONSE=$(curl -s -X POST "http://localhost:5050/api/v1/sessions/$SESSION_ID/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"prompt\": \"Analyze this report and describe the chart\",
    \"attachments\": [
      {\"file_id\": \"$FILE1_ID\", \"filename\": \"report.pdf\", \"content_type\": \"application/pdf\", \"is_image\": false, \"file_size\": 45230},
      {\"file_id\": \"$FILE2_ID\", \"filename\": \"chart.png\", \"content_type\": \"image/png\", \"is_image\": true, \"file_size\": 4580}
    ]
  }")

TASK_ID=$(echo "$TASK_RESPONSE" | jq -r '.task_id')

# 5. Poll for results
sleep 10
curl -s -X GET "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $TOKEN" | jq '.result'
```

---

### 3.14. Agent Pack Management

Agent packs are pre-configured bundles of profiles and collections that can be installed, shared, and managed as a unit. When deleting agent packs, all associated profiles and collections are removed, and active sessions using those resources are automatically archived.

#### 3.14.1. Check Active Sessions for Agent Pack

Check for active (non-archived) sessions that use any profiles or collections from a specific agent pack. Use this endpoint **before uninstalling** to warn users about sessions that will be archived.

**Endpoint:** `GET /api/v1/agent-packs/{installation_id}/check-sessions`
**Authentication:** Required (JWT or access token)
**Method:** `GET`
**Path Parameters:**
- `installation_id` (integer, required) - Agent pack installation ID

**Success Response:**
```json
{
  "status": "success",
  "active_session_count": 8,
  "active_sessions": [
    {
      "session_id": "df8ebb81-5f32-4d4a-be5a-47a036bec54f",
      "session_name": "Teradata Sales Analysis",
      "reason": "uses profile"
    },
    {
      "session_id": "a2b1c3d4-e5f6-7890-1234-567890abcdef",
      "session_name": "Product Database Query",
      "reason": "uses profile"
    }
  ],
  "profile_ids": [
    "profile-858e8b4c-940b-4689-8182-05a712242286",
    "profile-52f3d13d-edfb-4f74-8d07-e71a0d1356e7"
  ],
  "collection_ids": [
    "13",
    "14",
    "15"
  ]
}
```

**Response Fields:**
- `active_session_count` (integer) - Total number of active sessions affected
- `active_sessions` (array) - List of up to 5 active sessions (for display purposes)
    - `session_id` (string) - Session UUID
    - `session_name` (string) - User-friendly session name
    - `reason` (string) - Why this session is affected ("uses profile" or "uses collection")
- `profile_ids` (array) - List of profile IDs in this pack
- `collection_ids` (array) - List of collection IDs in this pack

**Use Case:**
- Call this endpoint before showing an uninstall confirmation dialog
- Display a dynamic warning like: "⚠️ Warning: 8 active sessions will be archived"
- Show sample session names to help users understand the impact
- List which profiles and collections will be removed

**Error Responses:**
- `401 Unauthorized` - Authentication required
- `404 Not Found` - Agent pack not found
- `500 Internal Server Error`

**Example:**
```bash
# Check active sessions before uninstalling agent pack
curl -X GET http://localhost:5050/api/v1/agent-packs/2/check-sessions \
  -H "Authorization: Bearer $TOKEN"

# Example: Dynamic confirmation message in UI
# If active_session_count > 0:
#   "⚠️ Warning: 8 active sessions will be archived."
#   "Affected sessions:"
#   "• Teradata Sales Analysis"
#   "• Product Database Query"
#   "...and 6 more"
```

#### 3.14.2. Uninstall Agent Pack

Uninstall an agent pack, removing all associated profiles and collections. All sessions using these resources are automatically archived.

**Endpoint:** `DELETE /api/v1/agent-packs/{installation_id}`
**Authentication:** Required (JWT or access token)
**Method:** `DELETE`
**Path Parameters:**
- `installation_id` (integer, required) - Agent pack installation ID

**Success Response:**
```json
{
  "status": "success",
  "profiles_deleted": 10,
  "collections_deleted": 9,
  "profiles_kept": 0,
  "collections_kept": 0,
  "sessions_archived": 8
}
```

**Response Fields:**
- `profiles_deleted` (integer) - Number of profiles removed
- `collections_deleted` (integer) - Number of collections removed
- `profiles_kept` (integer) - Profiles retained (shared with other packs)
- `collections_kept` (integer) - Collections retained (shared with other packs)
- `sessions_archived` (integer) - Number of sessions automatically archived

**Behavior:**
- All profiles and collections owned by this pack are deleted
- Resources shared with other installed packs are kept
- All sessions using deleted resources are automatically archived
- Archived sessions include reason and timestamp
- Cannot uninstall if a deleted profile is set as default (change default first)

**Error Responses:**
- `404 Not Found` - Agent pack not found
- `403 Forbidden` - Not the pack owner
- `400 Bad Request` - Cannot delete default profile
- `500 Internal Server Error`

**Example:**
```bash
# Uninstall agent pack
curl -X DELETE http://localhost:5050/api/v1/agent-packs/2 \
  -H "Authorization: Bearer $TOKEN"
```

---

## 4. Data Models

### 4.1. The Task Object

The Task Object is the central data structure for monitoring a query. It is returned by the `GET /api/v1/tasks/{task_id}` endpoint.

**Structure:**
```json
{
  "task_id": "string",
  "status": "string",
  "last_updated": "string (ISO 8601 UTC)",
  "events": [
    {
      "timestamp": "string (ISO 8601 UTC)",
      "event_data": { ... },
      "event_type": "string"
    }
  ],
  "intermediate_data": [
    {
      "tool_name": "string",
      "data": [ ... ]
    }
  ],
  "result": { ... }
}
```

**Fields:**
- `task_id`: Unique task identifier
- `status`: Task state (`pending`, `processing`, `complete`, `error`, `cancelled`, `cancelling`)
- `last_updated`: UTC timestamp of last update
- `events`: Chronological execution log
- `intermediate_data`: Tool call results as they are generated
- `result`: Final output (null until complete)

**Event Types:**

| Event Type       | Description                                    |
|------------------|------------------------------------------------|
| `plan_generated` | Strategic plan created or revised              |
| `phase_start`    | New phase of execution beginning               |
| `tool_result`    | Tool execution completed                       |
| `token_update`   | LLM tokens consumed                            |
| `workaround`     | Self-correction or optimization performed      |
| `cancelled`      | Execution stopped (user request)               |
| `error`          | Error occurred during execution                |

**Result Object Schemas:**

*CanonicalResponse* (standard queries):
```json
{
  "direct_answer": "string",
  "key_metric": { "value": "string", "label": "string" } | null,
  "key_observations": [ { "text": "string" } ],
  "synthesis": [ { "text": "string" } ]
}
```

*PromptReportResponse* (pre-defined prompts):
```json
{
  "title": "string",
  "executive_summary": "string",
  "report_sections": [
    { "title": "string", "content": "string (Markdown)" }
  ]
}
```

### 4.2. Authentication Token Comparison

| Feature | Access Tokens | JWT Tokens |
|---------|---------------|------------|
| **Format** | `tda_xxxxx...` (42 chars) | `eyJhbGci...` (variable) |
| **Lifetime** | Configurable or never | 24 hours fixed |
| **Use Case** | REST API, automation | Web UI sessions |
| **Storage** | SHA256 hashed | Stateless (not stored) |
| **Revocation** | Manual (instant) | Automatic (24h expiry) |
| **Tracking** | Use count, last used | No tracking |
| **Multiple** | Yes (per app/env) | One per session |
| **Security** | Shown once only | Regenerate on login |
| **Best For** | CI/CD, scripts, integrations | Interactive web use |

## 5. Code Examples

### 5.1. Complete Python Client

```python
#!/usr/bin/env python3
"""
Comprehensive TDA Python Client with access token management.
"""
import requests
import time
import os
from typing import Optional, Dict, Any

class TDAClient:
    """Uderia Platform API Client"""
    
    def __init__(self, base_url: str = "http://localhost:5050"):
        self.base_url = base_url.rstrip('/')
        self.jwt_token: Optional[str] = None
        self.access_token: Optional[str] = None
        self.session_id: Optional[str] = None
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authentication headers"""
        token = self.access_token or self.jwt_token
        if not token:
            raise Exception("Not authenticated. Call login() or set_access_token() first.")
        
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def register(self, username: str, email: str, password: str) -> Dict[str, Any]:
        """Register a new user account"""
        response = requests.post(
            f"{self.base_url}/auth/register",
            json={
                "username": username,
                "email": email,
                "password": password
            }
        )
        response.raise_for_status()
        return response.json()
    
    def login(self, username: str, password: str) -> bool:
        """Login and store JWT token"""
        response = requests.post(
            f"{self.base_url}/auth/login",
            json={"username": username, "password": password}
        )
        
        if response.status_code == 200:
            data = response.json()
            self.jwt_token = data.get("token")
            return True
        return False
    
    def set_access_token(self, token: str):
        """Set long-lived access token for authentication"""
        self.access_token = token
    
    def create_access_token(self, name: str, expires_in_days: Optional[int] = 90) -> Dict[str, Any]:
        """Create a new access token"""
        response = requests.post(
            f"{self.base_url}/api/v1/auth/tokens",
            headers=self._get_headers(),
            json={
                "name": name,
                "expires_in_days": expires_in_days
            }
        )
        response.raise_for_status()
        return response.json()
    
    def list_access_tokens(self) -> Dict[str, Any]:
        """List all access tokens"""
        response = requests.get(
            f"{self.base_url}/api/v1/auth/tokens",
            headers=self._get_headers()
        )
        response.raise_for_status()
        return response.json()
    
    def revoke_access_token(self, token_id: str) -> Dict[str, Any]:
        """Revoke an access token"""
        response = requests.delete(
            f"{self.base_url}/api/v1/auth/tokens/{token_id}",
            headers=self._get_headers()
        )
        response.raise_for_status()
        return response.json()
    
    def configure(self, provider: str, model: str, credentials: Dict[str, str], 
                  mcp_server: Dict[str, Any]) -> Dict[str, Any]:
        """Configure LLM and MCP server"""
        response = requests.post(
            f"{self.base_url}/api/v1/configure",
            json={
                "provider": provider,
                "model": model,
                "credentials": credentials,
                "mcp_server": mcp_server
            }
        )
        response.raise_for_status()
        return response.json()
    
    def create_session(self) -> str:
        """Create a new session and return session ID"""
        response = requests.post(
            f"{self.base_url}/api/v1/sessions",
            headers=self._get_headers()
        )
        response.raise_for_status()
        data = response.json()
        self.session_id = data.get("session_id")
        return self.session_id
    
    def submit_query(self, prompt: str, session_id: Optional[str] = None, 
                    profile_id: Optional[str] = None) -> Dict[str, Any]:
        """Submit a query and return task info
        
        Args:
            prompt: The natural language query
            session_id: Session ID (uses self.session_id if not provided)
            profile_id: Optional profile override (if omitted, uses default profile)
        
        Returns:
            Task information with task_id and status_url
        """
        sid = session_id or self.session_id
        if not sid:
            raise Exception("No session ID. Call create_session() first.")
        
        payload = {"prompt": prompt}
        if profile_id:
            payload["profile_id"] = profile_id
        
        response = requests.post(
            f"{self.base_url}/api/v1/sessions/{sid}/query",
            headers=self._get_headers(),
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get current task status"""
        response = requests.get(
            f"{self.base_url}/api/v1/tasks/{task_id}",
            headers=self._get_headers()
        )
        response.raise_for_status()
        return response.json()
    
    def wait_for_task(self, task_id: str, poll_interval: int = 2, 
                     max_wait: int = 300) -> Dict[str, Any]:
        """Wait for task completion with polling"""
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            task = self.get_task_status(task_id)
            status = task.get("status")
            
            if status in ["complete", "error", "cancelled"]:
                return task
            
            time.sleep(poll_interval)
        
        raise TimeoutError(f"Task {task_id} did not complete within {max_wait} seconds")
    
    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """Cancel a running task"""
        response = requests.post(
            f"{self.base_url}/api/v1/tasks/{task_id}/cancel",
            headers=self._get_headers()
        )
        response.raise_for_status()
        return response.json()
    
    def execute_query(self, prompt: str, session_id: Optional[str] = None, 
                     wait: bool = True, profile_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute a query and optionally wait for completion
        
        Args:
            prompt: The natural language query
            session_id: Session ID (uses self.session_id if not provided)
            wait: Whether to wait for completion
            profile_id: Optional profile override
        
        Returns:
            Task information or final result if wait=True
        """
        task_info = self.submit_query(prompt, session_id, profile_id)
        task_id = task_info.get("task_id")
        
        if wait:
            return self.wait_for_task(task_id)
        return task_info

# Usage Example
if __name__ == "__main__":
    # Initialize client
    client = TDAClient()
    
    # Option 1: Use access token (recommended)
    client.set_access_token(os.getenv("TDA_ACCESS_TOKEN"))
    
    # Option 2: Login with credentials
    # client.login("username", "password")
    
    # Create session and execute queries
    session_id = client.create_session()
    print(f"Created session: {session_id}")
    
    # Query 1: Using default profile
    result1 = client.execute_query("Show me all available databases")
    if result1["status"] == "complete":
        print("Query 1 completed with default profile!")
    
    # Query 2: Using profile override (execute same session with different profile)
    result2 = client.execute_query(
        "Tell me about the current configuration",
        profile_id="profile-1764006444002-z0hdduce9"  # Override with different profile
    )
    if result2["status"] == "complete":
        print("Query 2 completed with override profile!")
```
```

### 5.2. Bash/Shell Scripts

**Complete Automation Script:**
```bash
#!/bin/bash
# automated_analysis.sh - Daily database analysis automation

set -euo pipefail

# Configuration
TDA_URL="${TDA_URL:-http://localhost:5050}"
TDA_TOKEN="${TDA_ACCESS_TOKEN}"
DATABASE="${DATABASE:-production}"

if [ -z "$TDA_TOKEN" ]; then
    echo "Error: TDA_ACCESS_TOKEN environment variable not set"
    exit 1
fi

# Helper function for API calls
api_call() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"
    
    if [ -z "$data" ]; then
        curl -s -X "$method" "$TDA_URL$endpoint" \
            -H "Authorization: Bearer $TDA_TOKEN"
    else
        curl -s -X "$method" "$TDA_URL$endpoint" \
            -H "Authorization: Bearer $TDA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$data"
    fi
}

# Create session
echo "Creating session..."
SESSION_ID=$(api_call POST "/api/v1/sessions" | jq -r '.session_id')
echo "Session ID: $SESSION_ID"

# Submit query
echo "Submitting query..."
QUERY="Analyze the $DATABASE database and provide key metrics"
TASK_INFO=$(api_call POST "/api/v1/sessions/$SESSION_ID/query" \
    "{\"prompt\": \"$QUERY\"}")
TASK_ID=$(echo "$TASK_INFO" | jq -r '.task_id')
echo "Task ID: $TASK_ID"

# Poll for completion
echo "Waiting for results..."
while true; do
    TASK_STATUS=$(api_call GET "/api/v1/tasks/$TASK_ID")
    STATUS=$(echo "$TASK_STATUS" | jq -r '.status')
    
    echo "Status: $STATUS"
    
    if [ "$STATUS" = "complete" ]; then
        echo "✓ Query completed successfully"
        echo "$TASK_STATUS" | jq '.result'
        break
    elif [ "$STATUS" = "error" ]; then
        echo "✗ Query failed"
        echo "$TASK_STATUS" | jq '.result'
        exit 1
    elif [ "$STATUS" = "cancelled" ]; then
        echo "⚠ Query was cancelled"
        exit 1
    fi
    
    sleep 2
done
```

### 5.3. JavaScript/Node.js Client

```javascript
const axios = require('axios');

class TDAClient {
    constructor(baseURL = 'http://localhost:5050') {
        this.baseURL = baseURL;
        this.jwtToken = null;
        this.accessToken = null;
        this.sessionId = null;
    }
    
    getHeaders() {
        const token = this.accessToken || this.jwtToken;
        if (!token) {
            throw new Error('Not authenticated');
        }
        
        return {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        };
    }
    
    async register(username, email, password) {
        const response = await axios.post(
            `${this.baseURL}/auth/register`,
            { username, email, password }
        );
        return response.data;
    }
    
    async login(username, password) {
        try {
            const response = await axios.post(
                `${this.baseURL}/auth/login`,
                { username, password }
            );
            
            if (response.data.status === 'success') {
                this.jwtToken = response.data.token;
                return true;
            }
            return false;
        } catch (error) {
            console.error('Login failed:', error.message);
            return false;
        }
    }
    
    setAccessToken(token) {
        this.accessToken = token;
    }
    
    async createAccessToken(name, expiresInDays = 90) {
        const response = await axios.post(
            `${this.baseURL}/api/v1/auth/tokens`,
            { name, expires_in_days: expiresInDays },
            { headers: this.getHeaders() }
        );
        return response.data;
    }
    
    async createSession() {
        const response = await axios.post(
            `${this.baseURL}/api/v1/sessions`,
            {},
            { headers: this.getHeaders() }
        );
        this.sessionId = response.data.session_id;
        return this.sessionId;
    }
    
    async submitQuery(prompt, sessionId = null) {
        const sid = sessionId || this.sessionId;
        if (!sid) {
            throw new Error('No session ID');
        }
        
        const response = await axios.post(
            `${this.baseURL}/api/v1/sessions/${sid}/query`,
            { prompt },
            { headers: this.getHeaders() }
        );
        return response.data;
    }
    
    async getTaskStatus(taskId) {
        const response = await axios.get(
            `${this.baseURL}/api/v1/tasks/${taskId}`,
            { headers: this.getHeaders() }
        );
        return response.data;
    }
    
    async waitForTask(taskId, pollInterval = 2000, maxWait = 300000) {
        const startTime = Date.now();
        
        while (Date.now() - startTime < maxWait) {
            const task = await this.getTaskStatus(taskId);
            const status = task.status;
            
            if (['complete', 'error', 'cancelled'].includes(status)) {
                return task;
            }
            
            await new Promise(resolve => setTimeout(resolve, pollInterval));
        }
        
        throw new Error(`Task ${taskId} timeout after ${maxWait}ms`);
    }
    
    async executeQuery(prompt, sessionId = null, wait = true) {
        const taskInfo = await this.submitQuery(prompt, sessionId);
        const taskId = taskInfo.task_id;
        
        if (wait) {
            return await this.waitForTask(taskId);
        }
        return taskInfo;
    }
}

// Usage
(async () => {
    const client = new TDAClient();
    
    // Use access token
    client.setAccessToken(process.env.TDA_ACCESS_TOKEN);
    
    // Create session and execute query
    const sessionId = await client.createSession();
    console.log(`Created session: ${sessionId}`);
    
    const result = await client.executeQuery('Show me all databases');
    
    if (result.status === 'complete') {
        console.log('Query completed!');
        console.log('Result:', result.result);
    }
})();
```

### 5.4. cURL Examples

**Create Access Token:**
```bash
# Login first
JWT=$(curl -s -X POST http://localhost:5050/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"your_user","password":"your_pass"}' \
  | jq -r '.token')

# Create token
TOKEN=$(curl -s -X POST http://localhost:5050/api/v1/auth/tokens \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"Production","expires_in_days":90}' \
  | jq -r '.token')

echo "Your access token: $TOKEN"
echo "Save this token securely!"
```

**Complete Query Workflow:**
```bash
TOKEN="tda_your_token_here"

# Create session
SESSION=$(curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r '.session_id')

# Submit query
TASK=$(curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Show all databases"}' \
  | jq -r '.task_id')

# Poll for result
while true; do
    STATUS=$(curl -s http://localhost:5050/api/v1/tasks/$TASK \
      -H "Authorization: Bearer $TOKEN" \
      | jq -r '.status')
    
    if [ "$STATUS" = "complete" ]; then
        curl -s http://localhost:5050/api/v1/tasks/$TASK \
          -H "Authorization: Bearer $TOKEN" | jq '.result'
        break
    fi
    
    sleep 2
done
```

## 6. Security Best Practices

### 6.1. Token Storage

#### ✅ Recommended Approaches

**Environment Variables:**
```bash
# ~/.bashrc or ~/.zshrc
export TDA_ACCESS_TOKEN="tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p"
export TDA_BASE_URL="https://tda.company.com"
```

**.env Files (with .gitignore):**
```bash
# .env
TDA_ACCESS_TOKEN=tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
TDA_BASE_URL=https://tda.company.com
```

```python
# Python with python-dotenv
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv('TDA_ACCESS_TOKEN')
```

**Secret Managers:**
```python
# AWS Secrets Manager
import boto3
secrets = boto3.client('secretsmanager')
token = secrets.get_secret_value(SecretId='tda/access_token')['SecretString']

# Azure Key Vault
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
client = SecretClient(vault_url="https://myvault.vault.azure.net", 
                     credential=DefaultAzureCredential())
token = client.get_secret("tda-access-token").value
```

#### ❌ Bad Practices

```python
# DON'T hardcode tokens
TOKEN = "tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p"

# DON'T commit tokens to git
# DON'T store tokens in plain text files
# DON'T log tokens in application logs
# DON'T share tokens via email/chat
```

### 6.2. Network Security

**Use HTTPS in Production:**
```python
# ✅ Production
BASE_URL = "https://tda.company.com"

# ⚠️ Development only
BASE_URL = "http://localhost:5050"
```

**Certificate Verification:**
```python
import requests

# ✅ Verify certificates (default)
response = requests.get(url, verify=True)

# ⚠️ Only disable for local development
response = requests.get(url, verify=False)
```

### 6.3. Token Management

**Create Separate Tokens per Application:**
```bash
# Production server
TOKEN_PROD=$(create_token "Production Server" 90)

# Development server
TOKEN_DEV=$(create_token "Development Server" 30)

# CI/CD Pipeline
TOKEN_CI=$(create_token "CI/CD Pipeline" 365)
```

**Rotate Tokens Regularly:**
```bash
#!/bin/bash
# rotate_tokens.sh - Automate token rotation

OLD_TOKEN_ID="token-id-to-revoke"
NEW_TOKEN_NAME="Production Server ($(date +%Y-%m-%d))"

# Create new token
NEW_TOKEN=$(create_access_token "$NEW_TOKEN_NAME" 90)

# Update application configuration
update_app_config "$NEW_TOKEN"

# Verify new token works
test_api_with_token "$NEW_TOKEN"

# Revoke old token only after verification
revoke_token "$OLD_TOKEN_ID"
```

**Implement Token Expiration Handling:**
```python
import time

class TDAClient:
    def __init__(self):
        self.token = None
        self.token_expires_at = 0
    
    def is_token_valid(self):
        if not self.token:
            return False
        
        # For access tokens with known expiration
        if self.token_expires_at:
            return time.time() < self.token_expires_at
        
        return True
    
    def execute_with_retry(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Token expired - refresh/re-login
                self.refresh_authentication()
                return func(*args, **kwargs)
            raise
```

### 6.4. Rate Limiting

The API implements rate limiting to prevent abuse:

| Endpoint | Limit | Window |
|----------|-------|--------|
| `/auth/register` | 3 requests | 1 hour per IP |
| `/auth/login` | 5 requests | 1 minute per IP |
| All other endpoints | Varies | Based on usage |

**Handle Rate Limits:**
```python
import time

def api_call_with_backoff(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get('Retry-After', 60))
                print(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
            else:
                raise
    raise Exception("Max retries exceeded")
```

### 6.5. Audit Logging

**Monitor Token Usage:**
```python
def list_token_usage():
    tokens = client.list_access_tokens()
    
    for token in tokens['tokens']:
        print(f"Token: {token['name']}")
        print(f"  Created: {token['created_at']}")
        print(f"  Last Used: {token['last_used_at']}")
        print(f"  Use Count: {token['use_count']}")
        print(f"  Status: {'Active' if not token['revoked'] else 'Revoked'}")
        
        # Alert on suspicious usage
        if token['use_count'] > 10000:
            alert_security_team(f"High usage detected: {token['name']}")
```

### 6.6. Security Checklist

- [ ] All tokens stored securely (environment variables or secret managers)
- [ ] HTTPS enabled for all production connections
- [ ] Separate tokens created for each application/environment
- [ ] Token expiration set appropriately (90 days for production)
- [ ] Regular token rotation schedule implemented
- [ ] Monitoring and alerting for token usage
- [ ] Rate limit handling implemented
- [ ] No tokens committed to version control
- [ ] Certificate verification enabled
- [ ] Token revocation process documented

---

## 7. Troubleshooting

### 7.1. Authentication Errors

#### "Invalid or revoked access token"

**Cause:** Token doesn't exist, was revoked, or expired  
**Solution:**
```bash
# List your tokens to check status
curl -X GET http://localhost:5050/api/v1/auth/tokens \
  -H "Authorization: Bearer $JWT"

# Create new token if needed
curl -X POST http://localhost:5050/api/v1/auth/tokens \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"New Token","expires_in_days":90}'
```

#### "Authentication required"

**Cause:** Missing or malformed `Authorization` header  
**Solution:**
```bash
# ✅ Correct format
curl -H "Authorization: Bearer tda_xxxxx..."

# ❌ Common mistakes
curl -H "Authorization: tda_xxxxx..."        # Missing "Bearer "
curl -H "Authorization: Bearer tda_xxxxx ..."  # Extra space after token
curl -H "Authorization:Bearer tda_xxxxx..."  # Missing space after colon
```

#### "Token expired"

**Cause:** JWT token older than 24 hours  
**Solution:** Login again to get new JWT token

```python
# Implement auto-refresh
def ensure_authenticated(client):
    try:
        return client.some_api_call()
    except TokenExpiredError:
        client.login(username, password)
        return client.some_api_call()
```

### 7.2. Configuration Errors

#### "No default profile configured for this user"

**HTTP Status:** `400 Bad Request`

**Cause:** User doesn't have a default profile set up. REST operations require a profile that combines an LLM provider with an MCP server.

**Solution:** 
1. Configure a profile through the web UI:
   - Go to **Configuration** panel
   - Create LLM Configuration (Google, Anthropic, Azure, AWS, Friendli, or Ollama)
   - Create MCP Server Configuration (point to your data/tools)
   - Create Profile combining both
   - Mark Profile as **default** (star icon)

2. Or configure via REST API (see endpoints in Section 3.3)

#### "Profile is incomplete"

**HTTP Status:** `503 Service Unavailable`

**Cause:** Default profile exists but is missing LLM or MCP server configuration

**Solution:**
1. Edit the profile in Configuration UI
2. Ensure both LLM Configuration ID and MCP Server ID are set
3. Save the profile

#### "MCP server connection failed"

**Cause:** MCP server not running or incorrect configuration  
**Solution:**
1. Verify MCP server is running
2. Check host/port/path configuration in Profile settings
3. Test connection: `curl http://localhost:8001/mcp`

### 7.3. Query Execution Errors

#### "Invalid or non-existent profile_id"

**HTTP Status:** `400 Bad Request`

**Cause:** The `profile_id` specified in the query request doesn't exist or doesn't belong to the user

**Solution:**
1. Get your available profiles:
```bash
curl -X GET http://localhost:5050/api/v1/profiles \
  -H "Authorization: Bearer $TOKEN"
```

2. Use a valid profile ID from the list, or omit `profile_id` to use default:
```bash
# Without override (uses default profile)
curl -X POST http://localhost:5050/api/v1/sessions/{id}/query \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"prompt": "Your question"}'

# With valid override
curl -X POST http://localhost:5050/api/v1/sessions/{id}/query \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"prompt": "Your question", "profile_id": "profile-valid-id"}'
```

#### Task Status: "error"

**Cause:** Query execution failed  
**Solution:** Check the task `result` field for error details

```python
task = client.get_task_status(task_id)
if task['status'] == 'error':
    print("Error details:", task['result'])
    print("Events log:", task['events'])
```

#### Task Never Completes

**Cause:** Long-running query or server issue  
**Solution:**
1. Check task events for progress: `GET /api/v1/tasks/{task_id}`
2. Increase timeout in polling logic
3. Cancel and retry: `POST /api/v1/tasks/{task_id}/cancel`

### 7.4. Network Errors

#### "Connection refused"

**Cause:** TDA server not running or wrong URL  
**Solution:**
```bash
# Check if server is running
curl http://localhost:5050/

# Verify correct port
ps aux | grep trusted_data_agent

# Check logs
tail -f logs/tda.log
```

#### SSL/Certificate Errors

**Cause:** Self-signed certificate or expired cert  
**Solution:**
```python
# Development: Disable verification (not for production!)
import requests
import urllib3
urllib3.disable_warnings()
response = requests.get(url, verify=False)

# Production: Install proper certificate
# or add CA certificate to trusted store
```

### 7.5. Rate Limiting

#### "429 Too Many Requests"

**Cause:** Exceeded rate limits  
**Solution:**
```python
import time

def handle_rate_limit(response):
    if response.status_code == 429:
        retry_after = int(response.headers.get('Retry-After', 60))
        print(f"Rate limited. Waiting {retry_after} seconds...")
        time.sleep(retry_after)
        return True
    return False

# Use in requests
while True:
    response = requests.get(url, headers=headers)
    if not handle_rate_limit(response):
        break
```

### 7.6. Common Issues

#### "Session not found"

**Cause:** Session ID is invalid or expired  
**Solution:** Create new session

```python
session_id = client.create_session()
```

#### "Task not found"

**Cause:** Task ID is invalid or task was purged  
**Solution:** Submit query again

```python
task_info = client.submit_query(prompt)
task_id = task_info['task_id']
```

#### "Invalid JSON"

**Cause:** Malformed request body  
**Solution:** Validate JSON before sending

```python
import json

# Validate JSON
try:
    json.loads(request_body)
except json.JSONDecodeError as e:
    print(f"Invalid JSON: {e}")
```

### 7.7. Debugging Tips

**Enable Verbose Logging:**
```python
import logging
import http.client as http_client

http_client.HTTPConnection.debuglevel = 1
logging.basicConfig(level=logging.DEBUG)
```

**Inspect Full Response:**
```python
response = requests.post(url, headers=headers, json=data)
print("Status:", response.status_code)
print("Headers:", response.headers)
print("Body:", response.text)
```

**Test Authentication:**
```bash
# Verify token is valid
TOKEN="tda_your_token"
curl -v http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN"
```

### 7.8. Getting Help

If you continue to experience issues:

1. **Check the logs:** `logs/tda.log` on the server
2. **Verify configuration:** Web UI → Config tab
3. **Test basic connectivity:** `curl http://localhost:5050/`
4. **Check token status:** `GET /api/v1/auth/tokens`
5. **Review error events:** Check task `events` array for detailed execution logs

---

## 8. Quick Reference

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Register new user |
| POST | `/auth/login` | Login and get JWT |
| POST | `/auth/logout` | Logout (web UI) |
| POST | `/api/v1/auth/tokens` | Create access token |
| GET | `/api/v1/auth/tokens` | List access tokens |
| DELETE | `/api/v1/auth/tokens/{id}` | Revoke access token |

### Session & Query Endpoints

| Method | Endpoint | Description | Requires Profile |
|--------|----------|-------------|------------------|
| POST | `/api/v1/sessions` | Create new session | ✅ Yes (default) |
| GET | `/api/v1/sessions` | List sessions | ❌ No |
| GET | `/api/v1/sessions/{id}/details` | Get session details | ❌ No |
| POST | `/api/v1/sessions/{id}/query` | Submit query | ✅ Default (optional override) |
| GET | `/api/v1/tasks/{id}` | Get task status | ❌ No |
| POST | `/api/v1/tasks/{id}/cancel` | Cancel task | ❌ No |

**Profile Requirement Notes:**
- `POST /api/v1/sessions` requires user to have a **default profile** configured with both LLM Provider and MCP Server. Returns `400` if not configured.
- `POST /api/v1/sessions/{id}/query` uses the user's **default profile** by default. Accepts optional `profile_id` parameter in request body to override with a different profile. Each query can use a different profile within the same session, and the UI displays the correct profile badge for each message.

### RAG Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/rag/collections` | List collections |
| POST | `/api/v1/rag/collections` | Create collection |
| PUT | `/api/v1/rag/collections/{id}` | Update collection |
| DELETE | `/api/v1/rag/collections/{id}` | Delete collection |
| POST | `/api/v1/rag/collections/{id}/toggle` | Enable/disable |
| POST | `/api/v1/rag/collections/{id}/refresh` | Refresh vectors |
| POST | `/api/v1/rag/collections/{id}/populate` | Populate from template |
| GET | `/api/v1/rag/templates` | List templates |
| POST | `/api/v1/rag/generate-questions` | Generate Q&A pairs (MCP context) |
| POST | `/api/v1/rag/generate-questions-from-documents` | Generate Q&A pairs (documents) |

### HTTP Status Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| 200 | OK | Success |
| 201 | Created | Resource created |
| 202 | Accepted | Task submitted |
| 400 | Bad Request | Invalid parameters, no profile configured |
| 401 | Unauthorized | Missing/invalid token |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource doesn't exist |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Error | Server error |
| 503 | Service Unavailable | Profile incomplete (missing LLM or MCP) |

---

## 9. API Updates & Migration Notes

### Recent Changes (November 2025)

#### 🎯 Profile Override Feature - NEW
**What Changed:** `POST /api/v1/sessions/{id}/query` now accepts optional `profile_id` parameter for per-query profile override.

**What This Means:**
- Execute different queries in the same session with different profiles
- Each query can use a different LLM/MCP combination
- UI displays the correct profile badge for each message
- Provides complete visibility into which profile was used for each query

**Usage:**
```bash
# Query with default profile (no profile_id needed)
curl -X POST http://localhost:5050/api/v1/sessions/{id}/query \
  -d '{"prompt": "Your question"}'

# Query with profile override
curl -X POST http://localhost:5050/api/v1/sessions/{id}/query \
  -d '{"prompt": "Your question", "profile_id": "profile-xxx"}'
```

**Backward Compatibility:** ✅ Fully backward compatible. Existing code without `profile_id` will continue to work using the default profile.

**See Also:** Section 3.5.1 "Submit a Query" for complete details and examples.

#### 🔄 User-Scoped Sessions & Queries
**What Changed:** Sessions and queries are now fully user-scoped through JWT/access token authentication.

**Before:**
- Sessions could be created with just an Authorization header
- Optional `X-TDA-User-UUID` header to specify user (or default to system UUID)
- User isolation was not enforced at API level

**Now:**
- User identity is **always** extracted from the authentication token
- No custom headers needed - the system automatically associates all resources with the authenticated user
- 404 responses if you try to access another user's sessions
- **Migration:** Remove any `X-TDA-User-UUID` header usage from your clients

#### ✅ Unified Endpoint Paths
**What Changed:** All API endpoints now use consistent `/api/v1/` prefix.

**Impact:**
- Consistent path structure across all endpoints
- Documentation updated to reflect correct paths
- Both styles work during transition period, but use `/api/v1/` for new code

#### 🔐 Authentication Requirements
**What Changed:** All data-modifying operations now require authentication.

**Current Requirements:**
- `GET /api/v1/rag/collections` - Public (no auth)
- `POST/PUT/DELETE` operations - Require JWT or access token
- Session/query operations - Require authentication

### Migration Guide

**If you were using X-TDA-User-UUID header:**

Before:
```bash
curl -X GET http://localhost:5050/api/v1/sessions \
  -H "X-TDA-User-UUID: user-uuid-here" \
  -H "Authorization: Bearer $TOKEN"
```

After:
```bash
curl -X GET http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN"
```

The user UUID is now automatically extracted from your token. Remove the `X-TDA-User-UUID` header.

---

## 10. Additional Resources

- **Planner Repository Constructors:** `docs/RAG_Templates/README.md`
- **Authentication Migration:** `docs/AUTH_ONLY_MIGRATION.md`
- **Sample Configurations:** `docs/RestAPI/scripts/sample_configs/`
- **Example Scripts:** `docs/RestAPI/scripts/`
- **Main Documentation:** `README.md`

---

**Last Updated:** November 26, 2025  
**API Version:** v1  
**Document Version:** 2.1.0