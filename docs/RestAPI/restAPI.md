# Uderia Platform REST API Documentation

## Table of Contents

1. [Introduction](#1-introduction)
2. [Authentication](#2-authentication)
   - [Access Tokens (Recommended)](#21-access-tokens-recommended)
   - [JWT Tokens](#22-jwt-tokens)
   - [Quick Start Guide](#23-quick-start-guide)
3. [API Endpoints](#3-api-endpoints)
   - [Authentication Endpoints](#31-authentication-endpoints)
     - [OAuth Authentication](#314-oauth-authentication)
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
   - [Knowledge Repository Management](#315-knowledge-repository-management)
   - [LLM Configuration Management](#316-llm-configuration-management)
   - [Consumption & Analytics](#317-consumption--analytics)
   - [Cost Management](#318-cost-management)
   - [Genie Multi-Profile Coordination](#319-genie-multi-profile-coordination)
   - [Admin Endpoints](#320-admin-endpoints)
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

**1. Authenticate** - Obtain a JWT from `/api/v1/auth/login`, then create long-lived token via `/api/v1/auth/tokens`  
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
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
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
curl -X POST http://localhost:5050/api/v1/auth/register \
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
curl -X POST http://localhost:5050/api/v1/auth/login \
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

**Endpoint:** `POST /api/v1/auth/register`  
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

**Endpoint:** `POST /api/v1/auth/login`  
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

**Endpoint:** `POST /api/v1/auth/logout`  
**Authentication:** Required (JWT token)

**Success Response:**
```json
{
  "status": "success",
  "message": "Logged out successfully"
}
```

#### 3.1.4. OAuth Authentication

The platform supports OAuth 2.0 authentication with Google and GitHub providers. OAuth provides a secure, password-less login experience and allows users to link multiple authentication methods to a single account.

**Supported Providers:**
- Google OAuth 2.0
- GitHub OAuth 2.0

**OAuth Flow:**
1. User initiates OAuth login
2. Platform redirects to provider (Google/GitHub)
3. User authenticates with provider
4. Provider redirects back with authorization code
5. Platform exchanges code for access token
6. Platform creates or links user account
7. JWT token issued for platform access

---

##### Get Available OAuth Providers

Retrieve list of configured OAuth providers.

**Endpoint:** `GET /api/v1/auth/oauth/providers`
**Authentication:** None (public endpoint)

**Success Response:**
```json
{
  "status": "success",
  "providers": [
    {
      "name": "google",
      "display_name": "Google",
      "icon": "oauth-google",
      "enabled": true
    },
    {
      "name": "github",
      "display_name": "GitHub",
      "icon": "oauth-github",
      "enabled": true
    }
  ]
}
```

**Use Case:** Display OAuth login buttons in UI

---

##### Initiate OAuth Login Flow

Redirect user to OAuth provider authorization endpoint.

**Endpoint:** `GET /api/v1/auth/oauth/<provider>`
**Authentication:** None (public endpoint)

**Path Parameters:**
- `provider` (string, required): OAuth provider (`google` or `github`)

**Query Parameters:**
- `return_to` (string, optional): URL to redirect to after successful authentication

**Response:**
- **Redirect** (302): Redirects to OAuth provider authorization page
- **Error** (404): Provider not configured
- **Error** (500): Failed to build authorization URL

**Example:**
```bash
# Initiate Google OAuth login
curl -L "http://localhost:5050/api/v1/auth/oauth/google?return_to=/dashboard"

# User is redirected to Google login page
# After authentication, redirected back to platform callback
```

**Workflow:**
1. User clicks "Login with Google" button
2. Frontend redirects to `/api/v1/auth/oauth/google`
3. Backend generates OAuth state token (CSRF protection)
4. Backend redirects to Google authorization page
5. User authorizes application
6. Google redirects to callback endpoint with authorization code

---

##### OAuth Callback Handler

Handle OAuth callback from provider after user authorization.

**Endpoint:** `GET /api/v1/auth/oauth/<provider>/callback`
**Authentication:** None (public endpoint, validated via OAuth state)

**Path Parameters:**
- `provider` (string, required): OAuth provider (`google` or `github`)

**Query Parameters:**
- `code` (string, required): Authorization code from provider
- `state` (string, required): State parameter for CSRF protection
- `error` (string, optional): Error code if authorization failed

**Success Response:**
- **Redirect** (302): Redirects to application with JWT token in URL fragment or cookie
- **Response Body** (if API mode):
```json
{
  "status": "success",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "uuid": "123e4567-e89b-12d3-a456-426614174000",
    "username": "user@gmail.com",
    "email": "user@gmail.com",
    "tier": "user"
  },
  "new_account": false
}
```

**Error Responses:**
```json
// Invalid OAuth state (CSRF protection)
{
  "status": "error",
  "message": "Invalid OAuth state parameter"
}

// Authorization denied by user
{
  "status": "error",
  "message": "OAuth authorization was denied"
}

// Failed to exchange code for token
{
  "status": "error",
  "message": "Failed to exchange authorization code"
}
```

**Workflow:**
1. Provider redirects to `/oauth/<provider>/callback?code=...&state=...`
2. Backend validates state parameter
3. Backend exchanges authorization code for access token
4. Backend retrieves user profile from provider
5. Backend creates new user OR links to existing account
6. Backend issues JWT token
7. User redirected to application

---

##### Link OAuth Account

Link an OAuth provider to an existing authenticated user account.

**Endpoint:** `GET /api/v1/auth/oauth/<provider>/link`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `provider` (string, required): OAuth provider to link (`google` or `github`)

**Query Parameters:**
- `return_to` (string, optional): URL to redirect to after successful linking

**Response:**
- **Redirect** (302): Redirects to OAuth provider authorization page

**Example:**
```bash
# Link Google account to current user
curl -L "http://localhost:5050/api/v1/auth/oauth/google/link" \
  -H "Authorization: Bearer $JWT"

# User redirected to Google authorization page
# After authorization, OAuth account linked to current user
```

**Use Case:** User logged in with password wants to add Google login option

---

##### OAuth Link Callback

Handle OAuth callback for account linking.

**Endpoint:** `GET /api/v1/auth/oauth/<provider>/link/callback`
**Authentication:** Validated via OAuth state (contains user UUID)

**Path Parameters:**
- `provider` (string, required): OAuth provider (`google` or `github`)

**Query Parameters:**
- `code` (string, required): Authorization code from provider
- `state` (string, required): State parameter containing user UUID
- `error` (string, optional): Error code if authorization failed

**Success Response:**
```json
{
  "status": "success",
  "message": "OAuth account linked successfully",
  "provider": "google",
  "linked_email": "user@gmail.com"
}
```

**Error Responses:**
```json
// OAuth account already linked to another user
{
  "status": "error",
  "message": "This Google account is already linked to another user"
}

// OAuth account already linked to current user
{
  "status": "error",
  "message": "This Google account is already linked to your account"
}
```

**Client Behavior:**
- After successful linking, user can login with either password OR OAuth
- Multiple OAuth providers can be linked to same account
- User shown success message: "Google account linked successfully"

---

##### Disconnect OAuth Account

Remove OAuth provider link from user account.

**Endpoint:** `POST /api/v1/auth/oauth/<provider>/disconnect`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `provider` (string, required): OAuth provider to disconnect (`google` or `github`)

**Success Response:**
```json
{
  "status": "success",
  "message": "OAuth account disconnected successfully",
  "provider": "google"
}
```

**Error Responses:**
```json
// OAuth account not linked
{
  "status": "error",
  "message": "No Google account is linked to your account"
}

// Cannot disconnect last authentication method
{
  "status": "error",
  "message": "Cannot disconnect last authentication method. Please set a password first."
}
```

**Safety Rules:**
- User must have at least one authentication method (password OR OAuth)
- If user has only OAuth and no password, disconnect is blocked
- User shown warning: "Set password before disconnecting OAuth"

---

##### Get Linked OAuth Accounts

Retrieve all OAuth accounts linked to current user.

**Endpoint:** `GET /api/v1/auth/oauth/accounts`
**Authentication:** Required (JWT or access token)

**Success Response:**
```json
{
  "status": "success",
  "oauth_accounts": [
    {
      "provider": "google",
      "email": "user@gmail.com",
      "linked_at": "2025-11-25T10:00:00Z",
      "last_used": "2026-02-05T14:30:00Z"
    },
    {
      "provider": "github",
      "email": "user@users.noreply.github.com",
      "linked_at": "2025-12-01T12:00:00Z",
      "last_used": null
    }
  ],
  "has_password": true
}
```

**Response Fields:**
- `provider`: OAuth provider name (`google`, `github`)
- `email`: Email address from OAuth provider
- `linked_at`: Timestamp when OAuth account was linked
- `last_used`: Last login via this OAuth provider (null if never used)
- `has_password`: Whether user has password set (for disconnect safety)

**Use Case:** Display linked accounts in user profile settings

---

**OAuth Configuration:**

OAuth providers must be configured in `tda_config.json` or environment variables:

```json
{
  "oauth": {
    "google": {
      "client_id": "your-google-client-id.apps.googleusercontent.com",
      "client_secret": "your-google-client-secret",
      "redirect_uri": "http://localhost:5050/api/v1/auth/oauth/google/callback"
    },
    "github": {
      "client_id": "your-github-client-id",
      "client_secret": "your-github-client-secret",
      "redirect_uri": "http://localhost:5050/api/v1/auth/oauth/github/callback"
    }
  }
}
```

**Environment Variables (Alternative):**
```bash
GOOGLE_OAUTH_CLIENT_ID=your-google-client-id
GOOGLE_OAUTH_CLIENT_SECRET=your-google-client-secret
GITHUB_OAUTH_CLIENT_ID=your-github-client-id
GITHUB_OAUTH_CLIENT_SECRET=your-github-client-secret
```

**Setup Guide:** See `docs/OAuth/OAUTH.md` for detailed OAuth provider configuration.

---

#### 3.1.5. Verify Email Address

Verify a user's email address using a verification token sent via email.

**Endpoint:** `POST /api/v1/auth/verify-email`
**Authentication:** None (public endpoint, validated via token)

**Request Body:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "email": "user@example.com"
}
```

**Parameters:**
- `token` (string, required): Verification token from email
- `email` (string, required): Email address to verify

**Success Response:**
```json
{
  "status": "success",
  "message": "Email verified successfully",
  "user_id": 123
}
```

**Error Responses:**
```json
// Invalid or expired token
{
  "status": "error",
  "message": "Invalid or expired verification token"
}

// User not found
{
  "status": "error",
  "message": "User not found"
}
```

**Workflow:**
1. User registers account
2. System sends verification email with token
3. User clicks link in email: `https://app.com/verify?token=...&email=...`
4. Frontend calls this endpoint with token and email
5. Backend verifies token and marks email as verified
6. User can now login

**Client Behavior:**
- Show loading indicator: "Verifying email..."
- Success: Redirect to login page with message "Email verified! Please login."
- Failure: Show error with "Resend Verification Email" button

---

#### 3.1.6. Resend Verification Email

Resend email verification email to a user.

**Endpoint:** `POST /api/v1/auth/resend-verification-email`
**Authentication:** None (public endpoint)

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Parameters:**
- `email` (string, required): Email address to resend verification to

**Success Response:**
```json
{
  "status": "success",
  "message": "Verification email sent successfully"
}
```

**Error Responses:**
```json
// Email already verified
{
  "status": "error",
  "message": "Email is already verified"
}

// User not found
{
  "status": "error",
  "message": "No user found with that email address"
}

// Rate limit exceeded
{
  "status": "error",
  "message": "Verification email already sent recently. Please wait 5 minutes."
}
```

**Rate Limiting:**
- Maximum 1 email per 5 minutes per email address
- Prevents abuse/spam

**Client Behavior:**
- Show success message: "Verification email sent. Check your inbox."
- Disable button for 5 minutes after sending
- Show countdown: "Resend available in 4:32"

---

#### 3.1.7. Forgot Password (Initiate Reset)

Initiate password reset flow by sending a reset token to user's email.

**Endpoint:** `POST /api/v1/auth/forgot-password`
**Authentication:** None (public endpoint)

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Parameters:**
- `email` (string, required): Email address of account to reset

**Success Response:**
```json
{
  "status": "success",
  "message": "Password reset email sent if account exists"
}
```

**Security Note:**
- Always returns success even if email doesn't exist (prevents user enumeration)
- Only sends email if account exists
- Token expires after 1 hour

**Client Behavior:**
- Show generic success message: "If an account exists with that email, you will receive a password reset link."
- Do NOT reveal whether email exists or not (security)

---

#### 3.1.8. Reset Password (Complete Reset)

Complete password reset using token from email.

**Endpoint:** `POST /api/v1/auth/reset-password`
**Authentication:** None (public endpoint, validated via token)

**Request Body:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "email": "user@example.com",
  "new_password": "NewSecurePassword123!"
}
```

**Parameters:**
- `token` (string, required): Reset token from email
- `email` (string, required): Email address of account
- `new_password` (string, required): New password (minimum 8 characters)

**Password Requirements:**
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one number
- At least one special character (recommended but not enforced)

**Success Response:**
```json
{
  "status": "success",
  "message": "Password reset successfully"
}
```

**Error Responses:**
```json
// Invalid or expired token
{
  "status": "error",
  "message": "Invalid or expired reset token"
}

// Weak password
{
  "status": "error",
  "message": "Password does not meet requirements"
}
```

**Workflow:**
1. User clicks "Forgot Password"
2. Enters email, receives reset token via email
3. Clicks link in email: `https://app.com/reset-password?token=...&email=...`
4. Enters new password
5. Frontend calls this endpoint
6. Backend validates token and updates password
7. User redirected to login page

**Client Behavior:**
- After successful reset, show: "Password reset successfully. Please login with your new password."
- Automatically redirect to login page after 3 seconds

---

#### 3.1.9. Get Current User Profile

Retrieve profile information for the currently authenticated user.

**Endpoint:** `GET /api/v1/auth/me`
**Authentication:** Required (JWT or access token)

**Success Response:**
```json
{
  "status": "success",
  "user": {
    "uuid": "123e4567-e89b-12d3-a456-426614174000",
    "username": "john_doe",
    "email": "john@example.com",
    "email_verified": true,
    "tier": "developer",
    "created_at": "2025-11-25T10:00:00Z",
    "last_login": "2026-02-06T14:30:00Z",
    "profile_picture": null,
    "settings": {
      "theme": "dark",
      "notifications_enabled": true
    }
  }
}
```

**Response Fields:**
- `uuid`: Unique user identifier (used in API calls)
- `username`: Display name
- `email`: Account email address
- `email_verified`: Email verification status
- `tier`: Access tier (`user`, `developer`, `admin`, `enterprise`)
- `profile_picture`: URL to profile picture (null if not set)
- `settings`: User preferences

**Use Case:** Display user information in profile settings page

---

#### 3.1.10. Update Current User Profile

Update profile information for the currently authenticated user.

**Endpoint:** `PUT /api/v1/auth/me`
**Authentication:** Required (JWT or access token)

**Request Body (Partial Update):**
```json
{
  "username": "john_doe_updated",
  "email": "newemail@example.com",
  "settings": {
    "theme": "light",
    "notifications_enabled": false
  }
}
```

**Updatable Fields:**
- `username` (string, optional): New display name (3-50 characters)
- `email` (string, optional): New email address (triggers re-verification)
- `settings` (object, optional): User preferences
- `profile_picture` (string, optional): URL to new profile picture

**Success Response:**
```json
{
  "status": "success",
  "message": "Profile updated successfully",
  "user": {
    "uuid": "123e4567-e89b-12d3-a456-426614174000",
    "username": "john_doe_updated",
    "email": "newemail@example.com",
    "email_verified": false,
    "tier": "developer",
    "updated_at": "2026-02-06T14:35:00Z"
  }
}
```

**Email Change Behavior:**
- If email changed, `email_verified` set to `false`
- New verification email sent to new address
- Old email address remains active until new email verified

**Error Responses:**
```json
// Username already taken
{
  "status": "error",
  "message": "Username is already taken"
}

// Invalid email format
{
  "status": "error",
  "message": "Invalid email address"
}
```

---

#### 3.1.11. Get User Features

Retrieve available features for the current user's tier.

**Endpoint:** `GET /api/v1/auth/me/features`
**Authentication:** Required (JWT or access token)

**Success Response:**
```json
{
  "status": "success",
  "tier": "developer",
  "features": {
    "max_sessions": 10,
    "max_profiles": 20,
    "max_collections": 50,
    "max_prompts_per_month": 2000,
    "can_create_agent_packs": true,
    "can_publish_marketplace": false,
    "can_access_system_prompts": false,
    "can_use_oauth": true,
    "can_upload_documents": true,
    "document_upload_max_size_mb": 50,
    "max_tokens_per_query": 100000,
    "advanced_analytics": true,
    "custom_branding": false,
    "priority_support": false
  }
}
```

**Feature Matrix by Tier:**

| Feature | Free | User | Developer | Enterprise |
|---------|------|------|-----------|------------|
| Max Sessions | 3 | 5 | 10 | 50 |
| Max Profiles | 5 | 10 | 20 | ∞ |
| Max Collections | 10 | 25 | 50 | ∞ |
| Prompts/Month | 100 | 500 | 2000 | 10000 |
| Create Agent Packs | ❌ | ✅ | ✅ | ✅ |
| Publish Marketplace | ❌ | ❌ | ❌ | ✅ |
| System Prompts Access | ❌ | ❌ | ✅ | ✅ |
| Document Upload | ❌ | ✅ | ✅ | ✅ |
| Max Upload Size (MB) | - | 25 | 50 | 100 |

**Use Case:** Enable/disable UI features based on user tier

---

#### 3.1.12. Get User Panes

Retrieve visible UI panes for the current user's tier.

**Endpoint:** `GET /api/v1/auth/me/panes`
**Authentication:** Required (JWT or access token)

**Success Response:**
```json
{
  "status": "success",
  "tier": "developer",
  "panes": {
    "sessions": true,
    "profiles": true,
    "rag_collections": true,
    "knowledge_repositories": true,
    "mcp_servers": true,
    "llm_configurations": true,
    "system_prompts": false,
    "agent_packs": true,
    "marketplace": false,
    "analytics": true,
    "admin_panel": false,
    "consumption_tracking": true,
    "user_management": false
  }
}
```

**Pane Visibility by Tier:**

| Pane | Free | User | Developer | Enterprise | Admin |
|------|------|------|-----------|------------|-------|
| Sessions | ✅ | ✅ | ✅ | ✅ | ✅ |
| Profiles | ✅ | ✅ | ✅ | ✅ | ✅ |
| RAG Collections | ✅ | ✅ | ✅ | ✅ | ✅ |
| Knowledge Repositories | ❌ | ✅ | ✅ | ✅ | ✅ |
| MCP Servers | ✅ | ✅ | ✅ | ✅ | ✅ |
| LLM Configurations | ✅ | ✅ | ✅ | ✅ | ✅ |
| System Prompts | ❌ | ❌ | ✅ | ✅ | ✅ |
| Agent Packs | ❌ | ✅ | ✅ | ✅ | ✅ |
| Marketplace | ❌ | ❌ | ❌ | ✅ | ✅ |
| Analytics | ❌ | ✅ | ✅ | ✅ | ✅ |
| Admin Panel | ❌ | ❌ | ❌ | ❌ | ✅ |
| Consumption Tracking | ✅ | ✅ | ✅ | ✅ | ✅ |
| User Management | ❌ | ❌ | ❌ | ❌ | ✅ |

**Use Case:** Dynamically show/hide navigation menu items based on tier

**Client Behavior:**
- On app load, fetch panes and build navigation menu
- Hide panes where value is `false`
- Show upgrade prompt if user clicks disabled pane

---

#### 3.1.13. Change Password

Change password for the currently authenticated user.

**Endpoint:** `POST /api/v1/auth/change-password`
**Authentication:** Required (JWT or access token)

**Request Body:**
```json
{
  "current_password": "CurrentPassword123!",
  "new_password": "NewSecurePassword456!"
}
```

**Parameters:**
- `current_password` (string, required): User's current password for verification
- `new_password` (string, required): New password (minimum 8 characters)

**Success Response:**
```json
{
  "status": "success",
  "message": "Password changed successfully"
}
```

**Error Responses:**
```json
// Incorrect current password
{
  "status": "error",
  "message": "Current password is incorrect"
}

// Weak new password
{
  "status": "error",
  "message": "New password does not meet requirements"
}

// Same password
{
  "status": "error",
  "message": "New password must be different from current password"
}
```

**Client Behavior:**
- After successful change, show: "Password changed successfully"
- Optionally: Log out user and require re-login with new password
- Security best practice: Log out all sessions except current

---

#### 3.1.14. Refresh JWT Token

Refresh an expired or soon-to-expire JWT token.

**Endpoint:** `POST /api/v1/auth/refresh`
**Authentication:** Required (JWT token, even if expired within grace period)

**Request Body:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Parameters:**
- `refresh_token` (string, optional): Refresh token (if using refresh token flow)
- OR use expired JWT in Authorization header (if within grace period)

**Success Response:**
```json
{
  "status": "success",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "expires_at": "2026-02-07T14:30:00Z"
}
```

**Token Refresh Flow:**

**Option 1: Grace Period (Recommended)**
- JWT tokens have 24-hour expiry
- 5-minute grace period after expiry
- Within grace period, can refresh with expired token

**Option 2: Refresh Tokens**
- Long-lived refresh token (30 days)
- Exchange refresh token for new access token
- Refresh token rotated on each use

**Error Responses:**
```json
// Token expired beyond grace period
{
  "status": "error",
  "message": "Token expired. Please login again."
}

// Invalid refresh token
{
  "status": "error",
  "message": "Invalid refresh token"
}
```

**Client Behavior:**
- **Automatic refresh:** Before JWT expires (e.g., at 23 hours), call refresh endpoint
- **On 401 errors:** Try refresh once, then redirect to login if refresh fails
- **Store new token:** Replace old JWT with new token in local storage

**Implementation Example:**
```javascript
// Automatic token refresh (30 minutes before expiry)
setInterval(async () => {
  const token = localStorage.getItem('jwt');
  const expiresAt = parseJWT(token).exp;
  const now = Date.now() / 1000;

  // Refresh if token expires in less than 30 minutes
  if (expiresAt - now < 1800) {
    const newToken = await refreshToken(token);
    localStorage.setItem('jwt', newToken);
  }
}, 60000); // Check every minute
```

---

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
        * **Client Behavior** (Web UI):
            * "Show Archived" toggle automatically disables (hides archived sessions)
            * Sessions list automatically refreshes
            * If no active sessions remain, a new session is automatically created
            * User is redirected to the new session (seamless experience)
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

#### 3.7.8. Get Artifact Relationships (Unified Endpoint)

**NEW**: Get comprehensive relationship information for any artifact (collections, profiles, MCP servers, LLM configurations, agent packs). This unified endpoint provides deletion safety analysis and impact assessment.

* **Endpoint**: `GET /api/v1/artifacts/{artifact_type}/{artifact_id}/relationships`
* **Authentication**: Required (JWT or access token)
* **Method**: `GET`
* **URL Parameters**:
    * `artifact_type` (string, required): Type of artifact - one of:
        * `collection` - RAG/knowledge repositories
        * `profile` - Execution profiles
        * `agent-pack` - Agent pack installations
        * `mcp-server` - MCP server configurations
        * `llm-config` - LLM provider configurations
    * `artifact_id` (string, required): The artifact ID
* **Query Parameters**:
    * `include_archived` (boolean, optional, default: `false`): Include archived sessions in results
    * `limit` (integer, optional, default: `5`): Maximum number of sessions to return
    * `full` (boolean, optional, default: `false`): Include extended relationship metadata
* **Example Request**:
    ```bash
    curl -X GET "http://localhost:5050/api/v1/artifacts/collection/12/relationships?include_archived=true&limit=10" \
      -H "Authorization: Bearer $JWT"
    ```
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "artifact": {
            "type": "collection",
            "id": "12",
            "name": "Fitness Handbook (Imported)",
            "repository_type": "knowledge"
          },
          "relationships": {
            "sessions": {
              "active_count": 2,
              "archived_count": 3,
              "total_count": 5,
              "items": [
                {
                  "session_id": "90ad61c9-...",
                  "session_name": "Simple Chat Greeting",
                  "relationship_type": "profile_configuration",
                  "details": "Uses profile @FOCUS which has this collection configured",
                  "is_archived": false
                }
              ],
              "limit_applied": true,
              "has_more": false
            },
            "profiles": {
              "count": 1,
              "items": [
                {
                  "profile_id": "profile-default-rag",
                  "profile_name": "Focus on Fitness",
                  "profile_tag": "FOCUS",
                  "relationship_type": "knowledge_configuration"
                }
              ]
            },
            "agent_packs": {
              "count": 0,
              "items": []
            }
          },
          "deletion_info": {
            "can_delete": true,
            "blockers": [],
            "warnings": [
              "2 active sessions will be archived",
              "1 profile will lose access to this collection"
            ],
            "cascade_effects": {
              "active_sessions_archived": 2,
              "archived_sessions_affected": 3,
              "total_sessions_affected": 5,
              "profiles_affected": 1
            }
          }
        }
        ```
* **Relationship Types**:
    * **For Collections**:
        * `direct_reference` - Session directly uses this collection
        * `workflow_history` - Session queried this collection
        * `profile_configuration` - Session uses profile with collection configured
    * **For Profiles**:
        * `current_profile` - Session currently using this profile
        * `historical_profile` - Session used this profile in past
        * `genie_child` - Genie child session using this profile
    * **For MCP Servers**:
        * `profile_mcp_server` - Session uses profile connected to server
    * **For LLM Configurations**:
        * `profile_llm_config` - Session uses profile with LLM configuration
    * **For Agent Packs**:
        * `uses_pack_profile` - Session uses profile managed by pack
        * `uses_pack_collection` - Session uses collection managed by pack
* **Use Cases**:
    1. **Deletion Warnings**: Check relationships before deleting artifacts
    2. **Impact Analysis**: Understand what will be affected by changes
    3. **Dependency Visualization**: Build artifact dependency graphs
    4. **Audit Trail**: Track which sessions use which resources
* **Error Response**:
    * **Code**: `400 Bad Request` (invalid artifact type)
    * **Code**: `404 Not Found` (artifact not found)
* **Notes**:
    * Provides **single source of truth** for relationship detection
    * Used by both frontend deletion warnings and backend session archiving
    * Replaces older check-sessions endpoints (which remain for backward compatibility)

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

Delete an MCP server configuration. All sessions using profiles connected to this server are automatically archived.

* **Endpoint**: `DELETE /v1/mcp/servers/{server_id}`
* **Method**: `DELETE`
* **URL Parameters**:
    * `server_id` (string, required): The server ID
* **Success Response**:
    * **Code**: `200 OK`
    * **Content**:
        ```json
        {
          "status": "success",
          "message": "MCP server deleted successfully (5 sessions archived)",
          "archived_sessions": 5
        }
        ```
    * **Response Fields**:
        * `archived_sessions` (integer) - Number of sessions automatically archived
    * **Behavior**:
        * All sessions using profiles connected to this MCP server are archived
        * Archived sessions are marked with `archived: true`, timestamp, and reason
        * Sessions remain accessible but hidden by default (can be shown via "Show Archived" toggle)
        * **Client Behavior** (Web UI):
            * "Show Archived" toggle automatically disables (hides archived sessions)
            * Sessions list automatically refreshes
            * If no active sessions remain, a new session is automatically created
            * User is redirected to the new session (seamless experience)
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
- **Client Behavior** (Web UI):
    * "Show Archived" toggle automatically disables (hides archived sessions)
    * Sessions list automatically refreshes
    * If no active sessions remain, a new session is automatically created
    * User is redirected to the new session (seamless experience)

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
- **Client Behavior** (Web UI):
    * "Show Archived" toggle automatically disables (hides archived sessions)
    * Sessions list automatically refreshes
    * If no active sessions remain, a new session is automatically created
    * User is redirected to the new session (seamless experience)

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

#### 3.14.3. Import Agent Pack

Import an `.agentpack` file to install profiles and collections as a bundle.

**Endpoint:** `POST /api/v1/agent-packs/import`
**Authentication:** Required (JWT or access token)

**Request:** Multipart form data OR JSON

**Option 1: File Upload (multipart/form-data)**

**Form Fields:**
- `file` (file, required): `.agentpack` file to import
- `mcp_server_id` (string, optional): MCP server ID to associate profiles with
- `llm_configuration_id` (integer, optional): LLM configuration ID for profiles
- `conflict_strategy` (string, optional): How to handle conflicts (`skip`, `overwrite`, `rename`) (default: `skip`)

**Option 2: Local File Path (application/json)**

**Request Body:**
```json
{
  "import_path": "/path/to/pack.agentpack",
  "mcp_server_id": "mcp_server_123",
  "llm_configuration_id": 1,
  "conflict_strategy": "rename"
}
```

**Success Response:**
```json
{
  "status": "success",
  "installation_id": 5,
  "pack_name": "Sales Analytics Pack",
  "profiles_imported": 4,
  "collections_imported": 3,
  "conflicts_resolved": 1,
  "summary": {
    "profiles": ["Sales Dashboard", "Revenue Analysis", "Customer Insights", "Trend Forecasting"],
    "collections": ["Sales Queries", "Revenue Metrics", "Customer Data"]
  }
}
```

**Conflict Strategies:**
- `skip`: Skip conflicting resources (default)
- `overwrite`: Replace existing resources with imported versions
- `rename`: Rename imported resources to avoid conflicts (e.g., "Profile" → "Profile (2)")

**Error Responses:**
```json
// Invalid .agentpack file
{
  "status": "error",
  "message": "Invalid agent pack format: Missing manifest.json"
}

// File not found
{
  "status": "error",
  "message": "File not found: /path/to/pack.agentpack"
}
```

**Example:**
```bash
# Import via file upload
curl -X POST http://localhost:5050/api/v1/agent-packs/import \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sales-analytics.agentpack" \
  -F "mcp_server_id=mcp_server_123" \
  -F "conflict_strategy=rename"
```

**Client Behavior:**
- Show upload progress bar
- Display conflict resolution options if conflicts detected
- Refresh profiles and collections lists after import

---

#### 3.14.4. Export Agent Pack

Export a genie coordinator profile and its sub-profiles as an `.agentpack` file.

**Endpoint:** `POST /api/v1/agent-packs/export`
**Authentication:** Required (JWT or access token)

**Request Body:**
```json
{
  "coordinator_profile_id": "profile_123"
}
```

**Parameters:**
- `coordinator_profile_id` (string, required): ID of genie coordinator profile to export

**Response:** Binary `.agentpack` file download

**Response Headers:**
```
Content-Type: application/zip
Content-Disposition: attachment; filename="Sales_Analytics_Pack.agentpack"
```

**Export Contents:**
- `manifest.json` - Pack metadata (name, version, author, description)
- `profiles/` - All profiles (coordinator + sub-profiles)
- `collections/` - All associated RAG collections
- `README.md` - Usage documentation

**Error Responses:**
```json
// Profile not found
{
  "status": "error",
  "message": "Profile not found or not a genie coordinator"
}

// Not a genie profile
{
  "status": "error",
  "message": "Profile must be a genie coordinator to export as pack"
}
```

**Example:**
```bash
# Export agent pack
curl -X POST http://localhost:5050/api/v1/agent-packs/export \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"coordinator_profile_id": "profile_123"}' \
  --output sales-analytics.agentpack
```

**Use Case:** Share genie configurations with team members or publish to marketplace

---

#### 3.14.5. Create Agent Pack

Create a new agent pack from selected profiles and collections.

**Endpoint:** `POST /api/v1/agent-packs/create`
**Authentication:** Required (JWT or access token)

**Request Body:**
```json
{
  "name": "Customer Analytics Pack",
  "description": "Comprehensive customer data analysis tools",
  "version": "1.0.0",
  "author": "Analytics Team",
  "profile_ids": [1, 2, 3, 4],
  "collection_ids": [5, 6, 7],
  "metadata": {
    "category": "Analytics",
    "tags": ["customer", "analytics", "reporting"]
  }
}
```

**Parameters:**
- `name` (string, required): Pack name (3-100 characters)
- `description` (string, required): Pack description
- `version` (string, required): Semantic version (e.g., "1.0.0")
- `author` (string, optional): Author name
- `profile_ids` (array, required): Profile IDs to include
- `collection_ids` (array, optional): Collection IDs to include
- `metadata` (object, optional): Additional metadata

**Success Response:**
```json
{
  "status": "success",
  "installation_id": 6,
  "pack": {
    "name": "Customer Analytics Pack",
    "version": "1.0.0",
    "profiles_count": 4,
    "collections_count": 3,
    "created_at": "2026-02-06T15:00:00Z"
  }
}
```

---

#### 3.14.6. List Installed Agent Packs

Retrieve all agent packs installed for the current user.

**Endpoint:** `GET /api/v1/agent-packs`
**Authentication:** Required (JWT or access token)

**Success Response:**
```json
{
  "status": "success",
  "agent_packs": [
    {
      "installation_id": 1,
      "name": "Sales Analytics Pack",
      "version": "1.2.0",
      "author": "Analytics Team",
      "description": "Sales data analysis and forecasting tools",
      "profiles_count": 5,
      "collections_count": 4,
      "installed_at": "2026-01-15T10:00:00Z",
      "is_marketplace": false,
      "marketplace_id": null
    },
    {
      "installation_id": 2,
      "name": "Customer Insights Pack",
      "version": "2.0.1",
      "author": "CRM Team",
      "description": "Customer behavior analysis and segmentation",
      "profiles_count": 3,
      "collections_count": 2,
      "installed_at": "2026-02-01T14:30:00Z",
      "is_marketplace": true,
      "marketplace_id": "mp_abc123"
    }
  ],
  "total_packs": 2
}
```

---

#### 3.14.7. Get Agent Pack Details

Retrieve detailed information about a specific agent pack.

**Endpoint:** `GET /api/v1/agent-packs/{installation_id}`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `installation_id` (integer, required): Agent pack installation ID

**Success Response:**
```json
{
  "status": "success",
  "agent_pack": {
    "installation_id": 1,
    "name": "Sales Analytics Pack",
    "version": "1.2.0",
    "author": "Analytics Team",
    "description": "Comprehensive sales data analysis toolkit",
    "installed_at": "2026-01-15T10:00:00Z",
    "profiles": [
      {
        "id": 10,
        "name": "Sales Dashboard",
        "type": "tool_enabled",
        "is_default": false
      },
      {
        "id": 11,
        "name": "Revenue Analysis",
        "type": "rag_focused",
        "is_default": false
      }
    ],
    "collections": [
      {
        "id": 20,
        "name": "Sales Queries",
        "type": "planner",
        "entries_count": 45
      },
      {
        "id": 21,
        "name": "Revenue Metrics",
        "type": "knowledge",
        "entries_count": 120
      }
    ],
    "metadata": {
      "category": "Analytics",
      "tags": ["sales", "analytics", "revenue"],
      "license": "MIT"
    }
  }
}
```

---

#### 3.14.8. Publish Agent Pack to Marketplace

Publish an installed agent pack to the marketplace for sharing.

**Endpoint:** `POST /api/v1/agent-packs/{installation_id}/publish`
**Authentication:** Required (JWT or access token with Developer/Enterprise tier)

**Path Parameters:**
- `installation_id` (integer, required): Agent pack installation ID

**Request Body:**
```json
{
  "visibility": "public",
  "category": "Analytics",
  "tags": ["sales", "crm", "reporting"],
  "pricing": "free",
  "targeted_user_emails": []
}
```

**Parameters:**
- `visibility` (string, required): `public` or `private` (default: `private`)
- `category` (string, required): Marketplace category
- `tags` (array, optional): Search tags
- `pricing` (string, optional): `free` or `paid` (default: `free`)
- `targeted_user_emails` (array, optional): Email addresses for private sharing

**Success Response:**
```json
{
  "status": "success",
  "marketplace_id": "mp_abc123",
  "visibility": "public",
  "published_at": "2026-02-06T15:30:00Z",
  "marketplace_url": "https://marketplace.uderia.com/packs/mp_abc123"
}
```

**Authorization:**
- Requires `developer` or `enterprise` tier
- User must be pack owner

---

#### 3.14.9. Browse Marketplace Agent Packs

Browse available agent packs in the marketplace.

**Endpoint:** `GET /api/v1/marketplace/agent-packs`
**Authentication:** Required (JWT or access token)

**Query Parameters:**
- `category` (string, optional): Filter by category
- `search` (string, optional): Search query
- `sort_by` (string, optional): `popular`, `recent`, `rating` (default: `popular`)
- `limit` (integer, optional): Results per page (default: 20, max: 100)
- `offset` (integer, optional): Pagination offset

**Success Response:**
```json
{
  "status": "success",
  "marketplace_packs": [
    {
      "marketplace_id": "mp_abc123",
      "name": "Sales Analytics Pro",
      "version": "2.1.0",
      "author": "Analytics Corp",
      "description": "Professional sales analysis toolkit",
      "category": "Analytics",
      "tags": ["sales", "crm", "revenue"],
      "rating": 4.8,
      "downloads": 1247,
      "published_at": "2026-01-10T00:00:00Z",
      "updated_at": "2026-02-01T12:00:00Z",
      "is_installed": false,
      "pricing": "free"
    }
  ],
  "total_results": 45,
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total_pages": 3
  }
}
```

---

#### 3.14.10. Install Agent Pack from Marketplace

Install an agent pack from the marketplace.

**Endpoint:** `POST /api/v1/marketplace/agent-packs/{marketplace_id}/install`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `marketplace_id` (string, required): Marketplace pack ID

**Request Body:**
```json
{
  "mcp_server_id": "mcp_server_123",
  "llm_configuration_id": 1,
  "conflict_strategy": "rename"
}
```

**Success Response:**
```json
{
  "status": "success",
  "installation_id": 7,
  "pack_name": "Sales Analytics Pro",
  "profiles_imported": 6,
  "collections_imported": 5,
  "message": "Agent pack installed successfully"
}
```

---

#### 3.14.11. Fork Marketplace Agent Pack

Create a personal copy of a marketplace pack for customization.

**Endpoint:** `POST /api/v1/marketplace/agent-packs/{marketplace_id}/fork`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `marketplace_id` (string, required): Marketplace pack ID to fork

**Request Body:**
```json
{
  "new_name": "My Custom Sales Analytics",
  "mcp_server_id": "mcp_server_123",
  "llm_configuration_id": 1
}
```

**Success Response:**
```json
{
  "status": "success",
  "installation_id": 8,
  "forked_from": "mp_abc123",
  "new_pack_name": "My Custom Sales Analytics",
  "message": "Pack forked successfully. You can now customize it."
}
```

**Use Case:** Customize marketplace packs without affecting original

---

#### 3.14.12. Rate Marketplace Agent Pack

Submit a rating for a marketplace pack.

**Endpoint:** `POST /api/v1/marketplace/agent-packs/{marketplace_id}/rate`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `marketplace_id` (string, required): Marketplace pack ID

**Request Body:**
```json
{
  "rating": 5,
  "review": "Excellent pack! Saved us weeks of setup time."
}
```

**Parameters:**
- `rating` (integer, required): Rating 1-5 stars
- `review` (string, optional): Written review (max 500 characters)

**Success Response:**
```json
{
  "status": "success",
  "rating_submitted": 5,
  "new_average_rating": 4.7,
  "total_ratings": 89
}
```

---

#### 3.14.13. Unpublish Agent Pack from Marketplace

Remove an agent pack from the marketplace (pack owner only).

**Endpoint:** `DELETE /api/v1/marketplace/agent-packs/{marketplace_id}`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `marketplace_id` (string, required): Marketplace pack ID

**Success Response:**
```json
{
  "status": "success",
  "message": "Agent pack unpublished from marketplace",
  "installations_affected": 0
}
```

**Note:** Unpublishing doesn't affect users who already installed the pack.

---

#### 3.14.14. Get Targeted Users for Private Pack

Retrieve list of users who can access a private marketplace pack.

**Endpoint:** `GET /api/v1/marketplace/agent-packs/{marketplace_id}/targeted-users`
**Authentication:** Required (JWT or access token, pack owner only)

**Path Parameters:**
- `marketplace_id` (string, required): Marketplace pack ID

**Success Response:**
```json
{
  "status": "success",
  "targeted_users": [
    {
      "email": "john@company.com",
      "added_at": "2026-01-20T10:00:00Z",
      "has_installed": true
    },
    {
      "email": "jane@company.com",
      "added_at": "2026-01-25T14:30:00Z",
      "has_installed": false
    }
  ],
  "total_users": 2
}
```

---

#### 3.14.15. Update Targeted Users for Private Pack

Update the list of users who can access a private marketplace pack.

**Endpoint:** `PUT /api/v1/marketplace/agent-packs/{marketplace_id}/targeted-users`
**Authentication:** Required (JWT or access token, pack owner only)

**Path Parameters:**
- `marketplace_id` (string, required): Marketplace pack ID

**Request Body:**
```json
{
  "targeted_user_emails": [
    "john@company.com",
    "jane@company.com",
    "bob@partner.com"
  ],
  "action": "add"
}
```

**Parameters:**
- `targeted_user_emails` (array, required): Email addresses
- `action` (string, required): `add` or `remove` or `replace`

**Actions:**
- `add`: Add emails to existing list
- `remove`: Remove emails from list
- `replace`: Replace entire list with new emails

**Success Response:**
```json
{
  "status": "success",
  "targeted_users_count": 3,
  "action": "add",
  "message": "Targeted users updated successfully"
}
```

---

### 3.15. Knowledge Repository Management

Knowledge repositories store reference documents and domain knowledge that can be retrieved during query execution. Documents are chunked and embedded for semantic search via ChromaDB.

**Key Features:**
- Upload documents (PDF, TXT, DOCX, MD)
- Configurable chunking strategies (fixed_size, semantic, recursive)
- Semantic search with similarity scoring
- Document management (list, delete, retrieve chunks)
- Integration with RAG-focused profiles

---

#### 3.15.1. Preview Document Chunking

Preview how a document will be chunked before uploading to a knowledge repository.

**Endpoint:** `POST /api/v1/knowledge/preview-chunking`
**Authentication:** Required (JWT or access token)

**Request Body:**
```json
{
  "file_content": "Base64-encoded file content",
  "file_name": "technical_manual.pdf",
  "chunking_strategy": "recursive",
  "chunk_size": 1000,
  "chunk_overlap": 200
}
```

**Parameters:**
- `file_content` (string, required): Base64-encoded document content
- `file_name` (string, required): Original filename for format detection
- `chunking_strategy` (string, optional): `fixed_size`, `semantic`, or `recursive` (default: `recursive`)
- `chunk_size` (integer, optional): Target chunk size in characters (default: 1000)
- `chunk_overlap` (integer, optional): Overlap between chunks in characters (default: 200)

**Success Response:**
```json
{
  "status": "success",
  "preview": {
    "total_chunks": 45,
    "chunking_strategy": "recursive",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "sample_chunks": [
      {
        "chunk_id": 0,
        "content": "# Introduction\n\nThis technical manual covers...",
        "length": 982,
        "metadata": {
          "source": "technical_manual.pdf",
          "page": 1
        }
      },
      {
        "chunk_id": 1,
        "content": "## Installation\n\nTo install the system...",
        "length": 1045,
        "metadata": {
          "source": "technical_manual.pdf",
          "page": 2
        }
      }
    ],
    "file_metadata": {
      "file_name": "technical_manual.pdf",
      "file_size": 52480,
      "pages": 15
    }
  }
}
```

**Use Case:** Test chunking settings before uploading large document sets

---

#### 3.15.2. Upload Document to Repository

Upload a document to a knowledge repository with automatic chunking and embedding.

**Endpoint:** `POST /api/v1/knowledge/repositories/<id>/documents`
**Authentication:** Required (JWT or access token)

**Request:** Multipart form data

**Form Fields:**
- `file` (file, required): Document file to upload
- `chunking_strategy` (string, optional): `fixed_size`, `semantic`, or `recursive` (default: `recursive`)
- `chunk_size` (integer, optional): Target chunk size in characters (default: 1000)
- `chunk_overlap` (integer, optional): Overlap between chunks (default: 200)
- `metadata` (JSON string, optional): Additional metadata for the document

**Supported Formats:**
- PDF (`.pdf`)
- Text (`.txt`)
- Markdown (`.md`)
- Word Documents (`.docx`)

**Success Response:**
```json
{
  "status": "success",
  "document": {
    "document_id": "doc_abc123",
    "file_name": "technical_manual.pdf",
    "file_size": 52480,
    "pages": 15,
    "chunks_created": 45,
    "chunking_strategy": "recursive",
    "uploaded_at": "2026-02-06T14:30:00Z"
  },
  "repository_id": "repo_123"
}
```

**Error Responses:**
```json
// Unsupported file format
{
  "status": "error",
  "message": "Unsupported file format. Allowed: pdf, txt, docx, md"
}

// File too large
{
  "status": "error",
  "message": "File size exceeds maximum allowed size (50MB)"
}

// Repository not found
{
  "status": "error",
  "message": "Knowledge repository not found"
}
```

**Example:**
```bash
# Upload PDF document
curl -X POST "http://localhost:5050/api/v1/knowledge/repositories/repo_123/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@technical_manual.pdf" \
  -F "chunking_strategy=recursive" \
  -F "chunk_size=1000" \
  -F "chunk_overlap=200"
```

**Client Behavior:**
- Show upload progress bar (multipart upload)
- Display chunking progress: "Processing: 45/45 chunks created"
- Show success message: "Document uploaded successfully (45 chunks)"

---

#### 3.15.3. List Documents in Repository

Retrieve all documents in a knowledge repository.

**Endpoint:** `GET /api/v1/knowledge/repositories/<id>/documents`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (string, required): Repository ID

**Success Response:**
```json
{
  "status": "success",
  "repository_id": "repo_123",
  "documents": [
    {
      "document_id": "doc_abc123",
      "file_name": "technical_manual.pdf",
      "file_size": 52480,
      "pages": 15,
      "chunks_count": 45,
      "chunking_strategy": "recursive",
      "uploaded_at": "2026-02-06T14:30:00Z",
      "last_accessed": "2026-02-06T15:00:00Z"
    },
    {
      "document_id": "doc_def456",
      "file_name": "user_guide.docx",
      "file_size": 24320,
      "pages": 8,
      "chunks_count": 22,
      "chunking_strategy": "semantic",
      "uploaded_at": "2026-02-05T10:00:00Z",
      "last_accessed": null
    }
  ],
  "total_documents": 2,
  "total_chunks": 67
}
```

**Use Case:** Display document library in UI

---

#### 3.15.4. Delete Document from Repository

Remove a document and all its chunks from a knowledge repository.

**Endpoint:** `DELETE /api/v1/knowledge/repositories/<id>/documents/<doc_id>`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (string, required): Repository ID
- `doc_id` (string, required): Document ID to delete

**Success Response:**
```json
{
  "status": "success",
  "message": "Document deleted successfully",
  "document_id": "doc_abc123",
  "chunks_deleted": 45
}
```

**Client Behavior:**
- Show confirmation modal: "Delete 'technical_manual.pdf'? This will remove 45 chunks."
- After deletion, show: "Document deleted (45 chunks removed)"

---

#### 3.15.5. Search Knowledge Repository

Perform semantic search across all documents in a knowledge repository.

**Endpoint:** `POST /api/v1/knowledge/repositories/<id>/search`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (string, required): Repository ID

**Request Body:**
```json
{
  "query": "How do I configure SSL certificates?",
  "top_k": 5,
  "min_similarity": 0.6
}
```

**Parameters:**
- `query` (string, required): Search query
- `top_k` (integer, optional): Number of results to return (default: 3, max: 20)
- `min_similarity` (float, optional): Minimum similarity score (0.0-1.0, default: 0.6)

**Success Response:**
```json
{
  "status": "success",
  "query": "How do I configure SSL certificates?",
  "results": [
    {
      "chunk_id": "chunk_789",
      "document_id": "doc_abc123",
      "document_name": "technical_manual.pdf",
      "content": "## SSL Certificate Configuration\n\nTo configure SSL certificates, follow these steps:\n1. Generate a certificate signing request (CSR)...",
      "similarity": 0.92,
      "metadata": {
        "page": 12,
        "section": "Security Configuration"
      }
    },
    {
      "chunk_id": "chunk_456",
      "document_id": "doc_abc123",
      "document_name": "technical_manual.pdf",
      "content": "SSL/TLS certificates should be renewed every 90 days...",
      "similarity": 0.78,
      "metadata": {
        "page": 14,
        "section": "Maintenance"
      }
    }
  ],
  "total_results": 2,
  "search_metadata": {
    "min_similarity": 0.6,
    "top_k": 5,
    "chunks_searched": 67
  }
}
```

**Use Case:** Test repository before integrating with RAG-focused profile

---

#### 3.15.6. Get Document Chunks

Retrieve all chunks for a specific document in a knowledge collection.

**Endpoint:** `GET /api/v1/knowledge/collections/<id>/chunks`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (string, required): Collection ID

**Query Parameters:**
- `document_id` (string, optional): Filter chunks by document ID
- `page` (integer, optional): Page number for pagination (default: 1)
- `limit` (integer, optional): Chunks per page (default: 50, max: 200)

**Success Response:**
```json
{
  "status": "success",
  "collection_id": "col_789",
  "chunks": [
    {
      "chunk_id": "chunk_123",
      "document_id": "doc_abc123",
      "content": "# Introduction\n\nThis technical manual...",
      "metadata": {
        "source": "technical_manual.pdf",
        "page": 1,
        "section": "Introduction"
      },
      "embedding": null
    }
  ],
  "pagination": {
    "current_page": 1,
    "total_pages": 3,
    "total_chunks": 145,
    "limit": 50
  }
}
```

**Use Case:** Debug chunking issues, export document content

---

#### 3.15.7. Get Specific Chunk Details

Retrieve detailed information about a specific chunk.

**Endpoint:** `GET /api/v1/knowledge/collections/<id>/chunks/<chunk_id>`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (string, required): Collection ID
- `chunk_id` (string, required): Chunk ID

**Query Parameters:**
- `include_embedding` (boolean, optional): Include embedding vector (default: false)

**Success Response:**
```json
{
  "status": "success",
  "chunk": {
    "chunk_id": "chunk_123",
    "document_id": "doc_abc123",
    "document_name": "technical_manual.pdf",
    "content": "## SSL Certificate Configuration\n\nTo configure SSL certificates...",
    "length": 982,
    "metadata": {
      "source": "technical_manual.pdf",
      "page": 12,
      "section": "Security Configuration",
      "chunk_index": 23
    },
    "created_at": "2026-02-06T14:30:15Z",
    "embedding": null
  }
}
```

**With Embedding:**
```json
{
  "status": "success",
  "chunk": {
    ...other fields...,
    "embedding": [0.023, -0.145, 0.678, ..., 0.234],
    "embedding_model": "text-embedding-ada-002",
    "embedding_dimension": 1536
  }
}
```

**Use Case:** Inspect chunk quality, debug embedding issues

---

### 3.16. LLM Configuration Management

Manage LLM provider configurations including API keys, models, and settings. The system supports multiple providers simultaneously and encrypts all credentials.

**Supported Providers:**
- Google (Gemini 2.0)
- Anthropic (Claude)
- OpenAI (GPT-4o)
- Azure OpenAI
- AWS Bedrock
- Friendli.AI
- Ollama (local, offline)

**Key Features:**
- Encrypted credential storage (Fernet encryption)
- Provider-specific model selection
- Connection testing
- Active configuration management
- Automatic session archiving on deletion

---

#### 3.16.1. List LLM Configurations

Retrieve all LLM configurations for the current user.

**Endpoint:** `GET /api/v1/llm/configurations`
**Authentication:** Required (JWT or access token)

**Success Response:**
```json
{
  "status": "success",
  "configurations": [
    {
      "id": 1,
      "name": "Google Gemini Production",
      "provider": "google",
      "model": "gemini-2.0-flash-exp",
      "is_active": true,
      "created_at": "2025-11-25T10:00:00Z",
      "last_used": "2026-02-06T14:30:00Z"
    },
    {
      "id": 2,
      "name": "Claude Opus for Complex Queries",
      "provider": "anthropic",
      "model": "claude-opus-4-6",
      "is_active": false,
      "created_at": "2025-12-01T12:00:00Z",
      "last_used": "2026-01-15T09:00:00Z"
    }
  ],
  "active_configuration_id": 1,
  "total_configurations": 2
}
```

**Response Fields:**
- `is_active`: Whether this is the currently active LLM configuration
- `last_used`: Last time this configuration was used in a query
- **Security Note**: API keys and credentials are never returned

---

#### 3.16.2. Create LLM Configuration

Add a new LLM provider configuration.

**Endpoint:** `POST /api/v1/llm/configurations`
**Authentication:** Required (JWT or access token)

**Request Body (Google):**
```json
{
  "name": "Google Gemini Production",
  "provider": "google",
  "model": "gemini-2.0-flash-exp",
  "credentials": {
    "api_key": "AIzaSyD..."
  },
  "settings": {
    "temperature": 0.7,
    "max_tokens": 8192
  }
}
```

**Request Body (Anthropic):**
```json
{
  "name": "Claude Sonnet",
  "provider": "anthropic",
  "model": "claude-sonnet-4-5",
  "credentials": {
    "api_key": "sk-ant-..."
  },
  "settings": {
    "temperature": 1.0,
    "max_tokens": 8192
  }
}
```

**Request Body (Azure OpenAI):**
```json
{
  "name": "Azure GPT-4o",
  "provider": "azure",
  "model": "gpt-4o",
  "credentials": {
    "api_key": "your-azure-api-key",
    "endpoint": "https://your-resource.openai.azure.com/",
    "api_version": "2024-02-15-preview",
    "deployment_name": "gpt-4o-deployment"
  },
  "settings": {
    "temperature": 0.7
  }
}
```

**Request Body (AWS Bedrock):**
```json
{
  "name": "Bedrock Claude",
  "provider": "aws",
  "model": "anthropic.claude-v2",
  "credentials": {
    "aws_access_key_id": "AKIA...",
    "aws_secret_access_key": "your-secret-key",
    "region": "us-east-1"
  }
}
```

**Request Body (Ollama - Local):**
```json
{
  "name": "Ollama Llama3 Local",
  "provider": "ollama",
  "model": "llama3",
  "credentials": {
    "base_url": "http://localhost:11434"
  }
}
```

**Success Response:**
```json
{
  "status": "success",
  "configuration": {
    "id": 3,
    "name": "Google Gemini Production",
    "provider": "google",
    "model": "gemini-2.0-flash-exp",
    "is_active": false,
    "created_at": "2026-02-06T14:35:00Z"
  },
  "message": "LLM configuration created successfully"
}
```

**Validation Rules:**
- `name`: 3-100 characters, must be unique for user
- `provider`: Must be one of supported providers
- `model`: Must be valid for selected provider
- `credentials.api_key`: Required for cloud providers (automatically encrypted)

**Client Behavior:**
- API key input field shows masked characters: `••••••••••••••••`
- After creation, show: "Configuration created. Test connection before use."
- Credentials encrypted with Fernet before storage

---

#### 3.16.3. Get LLM Configuration Details

Retrieve detailed information about a specific LLM configuration.

**Endpoint:** `GET /api/v1/llm/configurations/<id>`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (integer, required): Configuration ID

**Success Response:**
```json
{
  "status": "success",
  "configuration": {
    "id": 1,
    "name": "Google Gemini Production",
    "provider": "google",
    "model": "gemini-2.0-flash-exp",
    "is_active": true,
    "settings": {
      "temperature": 0.7,
      "max_tokens": 8192
    },
    "created_at": "2025-11-25T10:00:00Z",
    "updated_at": "2026-01-10T14:00:00Z",
    "last_used": "2026-02-06T14:30:00Z",
    "usage_stats": {
      "total_queries": 1247,
      "total_tokens_input": 2456789,
      "total_tokens_output": 1234567,
      "total_cost": 45.67
    }
  }
}
```

**Security Note:** Credentials (API keys) are never returned in GET requests. To update credentials, use PUT endpoint.

---

#### 3.16.4. Update LLM Configuration

Update an existing LLM configuration (name, model, settings, or credentials).

**Endpoint:** `PUT /api/v1/llm/configurations/<id>`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (integer, required): Configuration ID

**Request Body (Partial Update):**
```json
{
  "name": "Google Gemini Production v2",
  "model": "gemini-2.0-pro-exp",
  "settings": {
    "temperature": 0.8
  }
}
```

**Request Body (Update Credentials):**
```json
{
  "credentials": {
    "api_key": "new-api-key-here"
  }
}
```

**Success Response:**
```json
{
  "status": "success",
  "message": "LLM configuration updated successfully",
  "configuration": {
    "id": 1,
    "name": "Google Gemini Production v2",
    "provider": "google",
    "model": "gemini-2.0-pro-exp",
    "updated_at": "2026-02-06T14:40:00Z"
  }
}
```

**Client Behavior:**
- If credentials updated, show: "Credentials updated. Test connection to verify."
- If model changed, show warning: "Model changed. Active sessions may be affected."

---

#### 3.16.5. Delete LLM Configuration

Delete an LLM configuration and archive all sessions using it.

**Endpoint:** `DELETE /api/v1/llm/configurations/<id>`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (integer, required): Configuration ID

**Success Response:**
```json
{
  "status": "success",
  "message": "LLM configuration deleted successfully",
  "sessions_archived": 15
}
```

**Error Responses:**
```json
// Configuration is in use by profiles
{
  "status": "error",
  "message": "Cannot delete LLM configuration in use by 3 profiles. Update profiles first."
}

// Configuration is active
{
  "status": "error",
  "message": "Cannot delete active LLM configuration. Activate another configuration first."
}
```

**Client Behavior:**
- **Before deletion:** Check if configuration is used by profiles
- **Show confirmation:** "Delete configuration? 15 sessions will be archived."
- **Session archiving:** All sessions using this LLM configuration are automatically archived
- **Archived reason:** "LLM configuration '{name}' was deleted"
- **After deletion:** Sessions list refreshes, archived sessions hidden by default

**Safety Rules:**
- Cannot delete active configuration (must activate another first)
- Cannot delete if used by profiles (must update profiles first)
- All sessions using configuration are archived (not deleted)

---

#### 3.16.6. Activate LLM Configuration

Set an LLM configuration as the active configuration for the current user.

**Endpoint:** `POST /api/v1/llm/configurations/<id>/activate`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (integer, required): Configuration ID to activate

**Success Response:**
```json
{
  "status": "success",
  "message": "LLM configuration activated",
  "configuration": {
    "id": 2,
    "name": "Claude Opus for Complex Queries",
    "provider": "anthropic",
    "model": "claude-opus-4-6",
    "is_active": true
  },
  "previous_active_id": 1
}
```

**Client Behavior:**
- Previous active configuration automatically deactivated
- Show success message: "Configuration '{name}' is now active"
- New sessions use this configuration by default

---

#### 3.16.7. Test LLM Configuration

Test connectivity and validate credentials for an LLM configuration.

**Endpoint:** `POST /api/v1/llm/configurations/<id>/test`
**Authentication:** Required (JWT or access token)

**Path Parameters:**
- `id` (integer, required): Configuration ID to test

**Success Response:**
```json
{
  "status": "success",
  "test_results": {
    "connection": "success",
    "model_available": true,
    "model": "gemini-2.0-flash-exp",
    "response_time_ms": 347,
    "test_query": "Respond with 'OK'",
    "test_response": "OK",
    "tokens_used": {
      "input": 5,
      "output": 2
    }
  },
  "message": "Connection test successful"
}
```

**Error Responses:**
```json
// Invalid API key
{
  "status": "error",
  "test_results": {
    "connection": "failed",
    "error": "Authentication failed: Invalid API key"
  },
  "message": "Connection test failed"
}

// Model not available
{
  "status": "error",
  "test_results": {
    "connection": "success",
    "model_available": false,
    "error": "Model 'gpt-4o' not found or not accessible"
  },
  "message": "Model not available"
}

// Network error
{
  "status": "error",
  "test_results": {
    "connection": "failed",
    "error": "Connection timeout after 10 seconds"
  },
  "message": "Connection test failed"
}
```

**Test Procedure:**
1. Decrypts stored API key
2. Sends test query to provider: "Respond with 'OK'"
3. Verifies response received
4. Checks model availability
5. Measures response time

**Client Behavior:**
- Show loading indicator during test: "Testing connection..."
- Success: Green checkmark + "Connection successful (347ms)"
- Failure: Red X + error message with retry button

**Use Case:** Verify configuration before setting as active

---

### 3.17. Consumption & Analytics

Track token usage, costs, and query analytics across sessions and users. The system provides detailed breakdowns by provider, model, profile, and time period.

**Key Features:**
- Real-time token counting from LLM responses
- Cost calculation with provider-specific pricing
- Per-user and system-wide analytics
- Historical data with time-based filtering
- Turn-by-turn consumption breakdown

---

#### 3.17.1. Get User Consumption Summary

Retrieve consumption summary for the current user.

**Endpoint:** `GET /api/v1/consumption/summary`
**Authentication:** Required (JWT or access token)

**Query Parameters:**
- `start_date` (string, optional): Filter from date (ISO 8601: `2026-01-01T00:00:00Z`)
- `end_date` (string, optional): Filter to date (ISO 8601: `2026-02-06T23:59:59Z`)
- `profile_id` (integer, optional): Filter by specific profile

**Success Response:**
```json
{
  "status": "success",
  "user_uuid": "123e4567-e89b-12d3-a456-426614174000",
  "summary": {
    "total_prompts": 347,
    "total_tokens": {
      "input": 1245678,
      "output": 876543,
      "total": 2122221
    },
    "total_cost": 12.34,
    "currency": "USD",
    "date_range": {
      "start": "2026-01-01T00:00:00Z",
      "end": "2026-02-06T23:59:59Z"
    }
  },
  "breakdown_by_provider": [
    {
      "provider": "google",
      "prompts": 200,
      "tokens": {"input": 800000, "output": 500000, "total": 1300000},
      "cost": 6.50,
      "models_used": ["gemini-2.0-flash-exp", "gemini-2.0-pro-exp"]
    },
    {
      "provider": "anthropic",
      "prompts": 147,
      "tokens": {"input": 445678, "output": 376543, "total": 822221},
      "cost": 5.84,
      "models_used": ["claude-sonnet-4-5", "claude-opus-4-6"]
    }
  ],
  "breakdown_by_profile": [
    {
      "profile_id": 1,
      "profile_name": "Default SQL Agent",
      "prompts": 250,
      "tokens": {"input": 950000, "output": 650000, "total": 1600000},
      "cost": 9.12
    },
    {
      "profile_id": 2,
      "profile_name": "Research Assistant",
      "prompts": 97,
      "tokens": {"input": 295678, "output": 226543, "total": 522221},
      "cost": 3.22
    }
  ]
}
```

**Use Case:** User dashboard showing consumption metrics

---

#### 3.17.2. Get System-Wide Consumption Summary (Admin)

Retrieve consumption summary for all users (admin only).

**Endpoint:** `GET /api/v1/consumption/system-summary`
**Authentication:** Required (JWT or access token with admin tier)

**Query Parameters:**
- `start_date` (string, optional): Filter from date
- `end_date` (string, optional): Filter to date

**Success Response:**
```json
{
  "status": "success",
  "system_summary": {
    "total_users": 24,
    "total_prompts": 5847,
    "total_tokens": {
      "input": 23456789,
      "output": 18765432,
      "total": 42222221
    },
    "total_cost": 256.78,
    "currency": "USD",
    "date_range": {
      "start": "2026-01-01T00:00:00Z",
      "end": "2026-02-06T23:59:59Z"
    }
  },
  "top_consumers": [
    {
      "user_uuid": "123e4567-...",
      "username": "data_analyst_john",
      "prompts": 1247,
      "tokens_total": 8456789,
      "cost": 62.34
    },
    {
      "user_uuid": "789e4567-...",
      "username": "research_team",
      "prompts": 987,
      "tokens_total": 6234567,
      "cost": 45.67
    }
  ],
  "breakdown_by_provider": [
    {
      "provider": "google",
      "prompts": 3200,
      "tokens_total": 25000000,
      "cost": 145.00
    },
    {
      "provider": "anthropic",
      "prompts": 2647,
      "tokens_total": 17222221,
      "cost": 111.78
    }
  ]
}
```

**Authorization:**
- Requires `admin` tier
- Returns 403 Forbidden for non-admin users

---

#### 3.17.3. Get All Users Consumption Data (Admin)

Retrieve detailed consumption data for all users (admin only).

**Endpoint:** `GET /api/v1/consumption/users`
**Authentication:** Required (JWT or access token with admin tier)

**Query Parameters:**
- `start_date` (string, optional): Filter from date
- `end_date` (string, optional): Filter to date
- `sort_by` (string, optional): Sort field (`prompts`, `tokens`, `cost`) (default: `cost`)
- `order` (string, optional): Sort order (`asc`, `desc`) (default: `desc`)
- `limit` (integer, optional): Number of users to return (default: 50, max: 200)

**Success Response:**
```json
{
  "status": "success",
  "users": [
    {
      "user_uuid": "123e4567-...",
      "username": "data_analyst_john",
      "email": "john@company.com",
      "tier": "developer",
      "consumption": {
        "prompts": 1247,
        "tokens": {"input": 4567890, "output": 3888899, "total": 8456789},
        "cost": 62.34
      },
      "quota_status": {
        "usage_percentage": 45.2,
        "prompts_remaining": 753,
        "reset_date": "2026-03-01T00:00:00Z"
      }
    },
    {
      "user_uuid": "789e4567-...",
      "username": "research_team",
      "email": "research@company.com",
      "tier": "enterprise",
      "consumption": {
        "prompts": 987,
        "tokens": {"input": 3234567, "output": 3000000, "total": 6234567},
        "cost": 45.67
      },
      "quota_status": {
        "usage_percentage": 12.3,
        "prompts_remaining": null,
        "reset_date": null
      }
    }
  ],
  "total_users": 24,
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total_pages": 1
  }
}
```

**Use Case:** Admin dashboard for monitoring user consumption and quota enforcement

---

#### 3.17.4. Get Consumption by Turns

Retrieve consumption broken down by individual conversation turns.

**Endpoint:** `GET /api/v1/consumption/turns`
**Authentication:** Required (JWT or access token)

**Query Parameters:**
- `session_id` (string, optional): Filter by specific session
- `start_date` (string, optional): Filter from date
- `end_date` (string, optional): Filter to date
- `limit` (integer, optional): Number of turns to return (default: 100, max: 500)

**Success Response:**
```json
{
  "status": "success",
  "turns": [
    {
      "turn_id": "turn_abc123",
      "session_id": "session_456",
      "profile_id": 1,
      "profile_name": "Default SQL Agent",
      "provider": "google",
      "model": "gemini-2.0-flash-exp",
      "user_query": "Show me all products with low inventory",
      "timestamp": "2026-02-06T14:30:00Z",
      "tokens": {
        "input": 3456,
        "output": 2345,
        "total": 5801
      },
      "cost": 0.042,
      "duration_ms": 2347,
      "success": true
    },
    {
      "turn_id": "turn_def456",
      "session_id": "session_789",
      "profile_id": 2,
      "profile_name": "Research Assistant",
      "provider": "anthropic",
      "model": "claude-sonnet-4-5",
      "user_query": "Summarize this technical document",
      "timestamp": "2026-02-06T13:15:00Z",
      "tokens": {
        "input": 8934,
        "output": 1234,
        "total": 10168
      },
      "cost": 0.156,
      "duration_ms": 4567,
      "success": true
    }
  ],
  "total_turns": 2,
  "summary": {
    "total_tokens": 15969,
    "total_cost": 0.198
  }
}
```

**Use Case:** Detailed consumption audit, identify expensive queries

---

#### 3.17.5. Get Consumption History

Retrieve historical consumption data with time-based aggregation.

**Endpoint:** `GET /api/v1/consumption/history`
**Authentication:** Required (JWT or access token)

**Query Parameters:**
- `start_date` (string, required): Start date (ISO 8601)
- `end_date` (string, required): End date (ISO 8601)
- `group_by` (string, optional): Aggregation interval (`hour`, `day`, `week`, `month`) (default: `day`)
- `timezone` (string, optional): Timezone for aggregation (default: `UTC`)

**Success Response:**
```json
{
  "status": "success",
  "history": [
    {
      "period": "2026-02-01",
      "prompts": 45,
      "tokens": {"input": 125678, "output": 98765, "total": 224443},
      "cost": 1.23,
      "sessions": 12
    },
    {
      "period": "2026-02-02",
      "prompts": 67,
      "tokens": {"input": 189012, "output": 145678, "total": 334690},
      "cost": 1.89,
      "sessions": 18
    },
    {
      "period": "2026-02-03",
      "prompts": 52,
      "tokens": {"input": 142345, "output": 112890, "total": 255235},
      "cost": 1.45,
      "sessions": 15
    }
  ],
  "total_periods": 6,
  "aggregation": {
    "group_by": "day",
    "timezone": "UTC"
  },
  "totals": {
    "prompts": 347,
    "tokens": {"input": 1245678, "output": 876543, "total": 2122221},
    "cost": 12.34
  }
}
```

**Use Case:** Generate consumption charts, trend analysis

---

#### 3.17.6. Get Session Analytics (Already Documented)

(See section 3.11.1 for full details)

**Endpoint:** `GET /api/v1/sessions/analytics`
**Authentication:** Required (JWT or access token)

**Brief Summary:**
Returns comprehensive analytics across all sessions including:
- Total sessions, tokens, success rate
- Average tokens per session
- Model usage breakdown
- Profile usage statistics

---

#### 3.17.7. Get User Quota Status

Retrieve current user's quota usage and limits.

**Endpoint:** `GET /api/v1/auth/user/quota-status`
**Authentication:** Required (JWT or access token)

**Success Response:**
```json
{
  "status": "success",
  "user_uuid": "123e4567-e89b-12d3-a456-426614174000",
  "tier": "developer",
  "quota": {
    "prompts_per_month": 2000,
    "prompts_used_this_month": 347,
    "prompts_remaining": 1653,
    "usage_percentage": 17.35,
    "reset_date": "2026-03-01T00:00:00Z",
    "days_until_reset": 22
  },
  "limits": {
    "max_tokens_per_query": 100000,
    "max_concurrent_sessions": 10,
    "rate_limit_per_hour": 100
  },
  "warnings": []
}
```

**With Warnings:**
```json
{
  ...other fields...,
  "warnings": [
    {
      "type": "approaching_limit",
      "message": "You have used 90% of your monthly prompt quota",
      "severity": "warning"
    }
  ]
}
```

**Quota Exceeded:**
```json
{
  "status": "error",
  "error": "quota_exceeded",
  "message": "Monthly prompt quota exceeded (2000/2000 used)",
  "quota": {
    "prompts_per_month": 2000,
    "prompts_used_this_month": 2000,
    "prompts_remaining": 0,
    "usage_percentage": 100.0,
    "reset_date": "2026-03-01T00:00:00Z"
  }
}
```

**Quota Tiers:**

| Tier | Prompts/Month | Max Tokens/Query | Concurrent Sessions |
|------|---------------|------------------|---------------------|
| Free | 100 | 50,000 | 3 |
| User | 500 | 75,000 | 5 |
| Developer | 2,000 | 100,000 | 10 |
| Enterprise | 10,000 | 200,000 | 50 |
| Unlimited | ∞ | 500,000 | ∞ |

**Client Behavior:**
- Display quota usage in header: "347 / 2000 prompts used (17%)"
- Show warning when > 80%: "Warning: 90% of quota used"
- Block new queries when quota exceeded: "Quota exceeded. Resets on March 1."

---

#### 3.17.8. Get User Consumption Summary (Alternate Endpoint)

**Endpoint:** `GET /api/v1/auth/user/consumption-summary`
**Authentication:** Required (JWT or access token)

**Note:** This endpoint provides similar functionality to `GET /api/v1/consumption/summary` but may have slight differences in response format. Prefer using `/api/v1/consumption/summary` for consistency.

**Success Response:**
```json
{
  "status": "success",
  "consumption": {
    "total_prompts": 347,
    "total_tokens_input": 1245678,
    "total_tokens_output": 876543,
    "total_cost": 12.34,
    "last_updated": "2026-02-06T14:30:00Z"
  }
}
```

---

#### 3.17.9. Cost Tracking Implementation Details

The platform tracks costs using a two-tier pricing system:

**1. LiteLLM Pricing Database:**
- Automatically syncs model pricing from LiteLLM's database
- Covers major providers (Google, Anthropic, OpenAI, Azure, AWS)
- Updated via `POST /api/v1/costs/sync` endpoint

**2. Manual Overrides:**
- Override pricing for specific models
- Set custom pricing for private/local models
- Fallback pricing for unknown models

**Cost Calculation:**
```python
input_cost = (input_tokens / 1_000_000) * model_input_price_per_1m
output_cost = (output_tokens / 1_000_000) * model_output_price_per_1m
total_cost = input_cost + output_cost
```

**Token Counting:**
- Tokens extracted from LLM provider responses (not pre-estimated)
- Per-turn and per-session accumulation
- Stored in database for historical analysis

**See Also:**
- Section 3.18 (Phase 2): Cost Management API endpoints
- `src/trusted_data_agent/core/cost_manager.py` for implementation

---

#### 3.17.10. Analytics Dashboard Data Flow

**Client-Side Flow:**
1. **Page Load:** Fetch `/api/v1/consumption/summary` and `/api/v1/consumption/history`
2. **Render Charts:** Use history data to render consumption trends
3. **Display Stats:** Show total prompts, tokens, cost from summary
4. **Poll for Updates:** Refresh every 60 seconds for real-time data

**Server-Side Flow:**
1. **Query Execution:** Tokens extracted from LLM response metadata
2. **Cost Calculation:** Apply pricing from `llm_model_costs` table
3. **Database Insert:** Store consumption data in `consumption_records` table
4. **Aggregation:** Analytics endpoints aggregate from `consumption_records`

**Performance Optimization:**
- Consumption data pre-aggregated by day for faster queries
- Indexes on `user_uuid`, `timestamp`, `provider` columns
- Caching of frequently accessed summaries (5-minute TTL)

---

### 3.18. Cost Management

Manage LLM pricing configurations, sync from LiteLLM, and analyze cost trends. Admin-only operations.

#### 3.18.1. Sync Costs from LiteLLM

**Endpoint:** `POST /api/v1/costs/sync`

**Authentication:** Admin only

**Description:** Syncs model pricing data from the LiteLLM pricing database and optionally checks model availability via LLM provider APIs.

**LiteLLM Integration:**
- Automatically fetches latest pricing from LiteLLM's model registry
- Handles provider-specific pricing variations (Google, Anthropic, OpenAI, Azure, etc.)
- Preserves manual overrides (entries with `is_manual_override: true`)
- Updates deprecated status based on provider API responses

**Request Body:**
```json
{
  "check_availability": true  // Optional, default: true
}
```

**Request Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `check_availability` | boolean | No | Check model availability via provider APIs (default: true) |

**Response (200 OK):**
```json
{
  "status": "success",
  "pricing": {
    "synced_count": 127,
    "new_models": 5,
    "updated_models": 12
  },
  "availability": {
    "checked": true,
    "deprecated_count": 3,
    "undeprecated_count": 1,
    "skipped_providers": ["Azure", "Ollama"]
  },
  "warnings": [
    "Failed to check availability for provider 'Azure': No API key configured"
  ]
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pricing.synced_count` | integer | Total number of models synced from LiteLLM |
| `pricing.new_models` | integer | Count of newly discovered models |
| `pricing.updated_models` | integer | Count of models with updated pricing |
| `availability.deprecated_count` | integer | Models marked as deprecated (not returned by provider API) |
| `availability.undeprecated_count` | integer | Previously deprecated models now available again |
| `availability.skipped_providers` | array | Providers skipped due to missing credentials |
| `warnings` | array | Non-fatal errors during sync (e.g., API failures) |

**Example:**
```bash
curl -X POST http://localhost:5050/api/v1/costs/sync \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"check_availability": true}'
```

**Manual Override Preservation:**

When syncing from LiteLLM, entries marked as manual overrides are **not updated**:
- Allows custom pricing for private LLM deployments
- Prevents overwriting organization-specific negotiated rates
- Use `PUT /api/v1/costs/models/<cost_id>` to update manual entries

**Use Cases:**
1. **Regular maintenance**: Sync weekly to get latest pricing updates
2. **After adding LLM config**: Sync to get pricing for new provider
3. **Troubleshooting costs**: Re-sync to fix missing/incorrect pricing

**Error Responses:**

| Status Code | Description | Example Response |
|-------------|-------------|------------------|
| 401 | Not authenticated | `{"status": "error", "message": "JWT token missing"}` |
| 403 | Not admin user | `{"status": "error", "message": "Admin access required"}` |
| 500 | Sync failed | `{"status": "error", "message": "LiteLLM API unavailable"}` |

---

#### 3.18.2. Get All Model Costs

**Endpoint:** `GET /api/v1/costs/models`

**Authentication:** Admin only

**Description:** Retrieves all model pricing entries from the database, including provider, model name, input/output costs, and metadata.

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `include_fallback` | boolean | No | `true` | Include fallback entry for unknown models |

**Response (200 OK):**
```json
{
  "status": "success",
  "count": 127,
  "costs": [
    {
      "id": "google_gemini-2.0-flash-001",
      "provider": "Google",
      "model": "gemini-2.0-flash-001",
      "input_cost_per_million": 0.075,
      "output_cost_per_million": 0.30,
      "is_manual_override": false,
      "is_deprecated": false,
      "notes": "Synced from LiteLLM",
      "updated_at": "2026-02-06T10:30:00Z"
    },
    {
      "id": "anthropic_claude-opus-4-6",
      "provider": "Anthropic",
      "model": "claude-opus-4-6",
      "input_cost_per_million": 15.0,
      "output_cost_per_million": 75.0,
      "is_manual_override": true,
      "is_deprecated": false,
      "notes": "Custom enterprise pricing",
      "updated_at": "2026-01-15T14:20:00Z"
    },
    {
      "id": "FALLBACK",
      "provider": "FALLBACK",
      "model": "FALLBACK",
      "input_cost_per_million": 10.0,
      "output_cost_per_million": 30.0,
      "is_manual_override": false,
      "is_deprecated": false,
      "notes": "Default pricing for unknown models",
      "updated_at": "2025-12-01T08:00:00Z"
    }
  ]
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (format: `{provider}_{model}`) |
| `provider` | string | LLM provider name (Google, Anthropic, OpenAI, etc.) |
| `model` | string | Model identifier (e.g., `gemini-2.0-flash-001`) |
| `input_cost_per_million` | float | Cost per 1M input tokens in USD |
| `output_cost_per_million` | float | Cost per 1M output tokens in USD |
| `is_manual_override` | boolean | Whether this is a manually added/modified entry |
| `is_deprecated` | boolean | Whether the model is no longer available |
| `notes` | string | Optional notes about pricing source or changes |
| `updated_at` | string (ISO 8601) | Last update timestamp |

**Example:**
```bash
curl -X GET "http://localhost:5050/api/v1/costs/models?include_fallback=true" \
  -H "Authorization: Bearer $JWT"
```

**Filtering:**

To exclude the fallback entry (useful for UI dropdowns):
```bash
curl -X GET "http://localhost:5050/api/v1/costs/models?include_fallback=false" \
  -H "Authorization: Bearer $JWT"
```

**Use Cases:**
1. **Cost auditing**: Review all model pricing before budget planning
2. **UI population**: Load pricing for cost calculator interfaces
3. **Manual override verification**: Identify which entries have custom pricing

---

#### 3.18.3. Update Model Cost (Manual Override)

**Endpoint:** `PUT /api/v1/costs/models/{cost_id}`

**Authentication:** Admin only

**Description:** Updates pricing for a specific model entry. Marks the entry as a manual override to prevent LiteLLM sync from overwriting it.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `cost_id` | string | Cost entry ID (format: `{provider}_{model}`) |

**Request Body:**
```json
{
  "input_cost": 0.080,
  "output_cost": 0.35,
  "notes": "Updated from official Google pricing page 2026-02-06"
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input_cost` | float | Yes | Cost per 1M input tokens (USD) |
| `output_cost` | float | Yes | Cost per 1M output tokens (USD) |
| `notes` | string | No | Optional notes about the override reason |

**Response (200 OK):**
```json
{
  "status": "success",
  "message": "Model cost updated"
}
```

**Example:**
```bash
curl -X PUT http://localhost:5050/api/v1/costs/models/google_gemini-2.0-flash-001 \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "input_cost": 0.080,
    "output_cost": 0.35,
    "notes": "Updated from official docs"
  }'
```

**Behavior:**
- Sets `is_manual_override: true` on the entry
- LiteLLM sync will **not** overwrite this entry in future syncs
- To revert to LiteLLM pricing: delete the entry and re-sync

**Use Cases:**
1. **Private LLM deployments**: Set custom pricing for internal models
2. **Negotiated rates**: Override with organization-specific pricing
3. **Pricing corrections**: Fix incorrect LiteLLM data
4. **Cost modeling**: Test different pricing scenarios

**Error Responses:**

| Status Code | Description | Example Response |
|-------------|-------------|------------------|
| 400 | Missing required fields | `{"status": "error", "message": "input_cost and output_cost are required"}` |
| 404 | Cost entry not found | `{"status": "error", "message": "Model cost entry not found"}` |

---

#### 3.18.4. Add Manual Model Cost

**Endpoint:** `POST /api/v1/costs/models`

**Authentication:** Admin only

**Description:** Adds a new pricing entry for a model not in the LiteLLM database (e.g., private deployments, custom models, or preview models).

**Request Body:**
```json
{
  "provider": "Google",
  "model": "gemini-2.5-flash-preview",
  "input_cost": 0.075,
  "output_cost": 0.30,
  "notes": "Preview model pricing from beta program"
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `provider` | string | Yes | Provider name (must match LLM config provider) |
| `model` | string | Yes | Model identifier |
| `input_cost` | float | Yes | Cost per 1M input tokens (USD) |
| `output_cost` | float | Yes | Cost per 1M output tokens (USD) |
| `notes` | string | No | Optional notes about pricing source |

**Response (201 Created):**
```json
{
  "status": "success",
  "cost_id": "google_gemini-2.5-flash-preview",
  "message": "Model cost added"
}
```

**Example:**
```bash
curl -X POST http://localhost:5050/api/v1/costs/models \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "Google",
    "model": "gemini-2.5-flash-preview",
    "input_cost": 0.075,
    "output_cost": 0.30,
    "notes": "Preview model pricing"
  }'
```

**Behavior:**
- Creates new entry with `is_manual_override: true`
- Entry is protected from LiteLLM sync overwriting
- Cost entry becomes active immediately for cost calculations

**Use Cases:**
1. **Private models**: Add pricing for self-hosted LLMs (Ollama, custom deployments)
2. **Preview models**: Track costs for beta/preview models not yet in LiteLLM
3. **Custom providers**: Add pricing for organization-specific LLM endpoints
4. **Testing**: Add dummy entries for cost calculation testing

**Error Responses:**

| Status Code | Description | Example Response |
|-------------|-------------|------------------|
| 400 | Missing required fields | `{"status": "error", "message": "provider, model, input_cost, and output_cost are required"}` |
| 409 | Entry already exists | `{"status": "error", "message": "Model cost entry already exists"}` |

**Duplicate Prevention:**

If an entry with the same `provider` and `model` already exists:
- POST returns 409 Conflict
- Use `PUT /api/v1/costs/models/{cost_id}` to update instead

---

#### 3.18.5. Delete Model Cost

**Endpoint:** `DELETE /api/v1/costs/models/{cost_id}`

**Authentication:** Admin only

**Description:** Deletes a model pricing entry. Cannot delete the fallback entry (use `PUT /api/v1/costs/fallback` to modify fallback pricing).

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `cost_id` | string | Cost entry ID (format: `{provider}_{model}`) |

**Response (200 OK):**
```json
{
  "status": "success",
  "message": "Model cost deleted"
}
```

**Example:**
```bash
curl -X DELETE http://localhost:5050/api/v1/costs/models/google_gemini-1.5-pro \
  -H "Authorization: Bearer $JWT"
```

**Behavior:**
- Permanently removes the pricing entry from database
- Future cost calculations will use fallback pricing for this model
- To restore LiteLLM pricing: run `POST /api/v1/costs/sync` after deletion

**Protected Entries:**

The following entries **cannot** be deleted:
- `FALLBACK` entry (use `PUT /api/v1/costs/fallback` instead)

**Use Cases:**
1. **Remove deprecated models**: Clean up entries for discontinued models
2. **Revert manual overrides**: Delete custom entry to restore LiteLLM pricing (then sync)
3. **Database cleanup**: Remove test or incorrect entries

**Error Responses:**

| Status Code | Description | Example Response |
|-------------|-------------|------------------|
| 404 | Entry not found or protected | `{"status": "error", "message": "Model cost entry not found or cannot be deleted"}` |

**Client Behavior:**

After deleting a model cost entry:
- Re-fetch the costs list via `GET /api/v1/costs/models`
- If the model is still in use, warn the user that fallback pricing will apply
- Consider syncing from LiteLLM to restore default pricing

---

#### 3.18.6. Update Fallback Cost

**Endpoint:** `PUT /api/v1/costs/fallback`

**Authentication:** Admin only

**Description:** Updates the fallback pricing used for unknown models (models not in the `llm_model_costs` table). This provides a conservative cost estimate when exact pricing is unavailable.

**Request Body:**
```json
{
  "input_cost": 10.0,
  "output_cost": 30.0
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input_cost` | float | Yes | Fallback cost per 1M input tokens (USD) |
| `output_cost` | float | Yes | Fallback cost per 1M output tokens (USD) |

**Response (200 OK):**
```json
{
  "status": "success",
  "message": "Fallback cost updated"
}
```

**Example:**
```bash
curl -X PUT http://localhost:5050/api/v1/costs/fallback \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "input_cost": 15.0,
    "output_cost": 45.0
  }'
```

**Default Fallback Values:**

| Pricing Tier | Input Cost | Output Cost | Rationale |
|--------------|------------|-------------|-----------|
| Default | $10.00 | $30.00 | Conservative estimate (Opus-level pricing) |
| Custom | User-defined | User-defined | Organization-specific safety margin |

**When Fallback is Used:**

1. **New preview models**: Model name not yet added to LiteLLM database
2. **Private deployments**: Custom model identifiers (e.g., `ollama/custom-model`)
3. **Typos in model names**: Incorrect model identifier in LLM config
4. **Sync failures**: LiteLLM database temporarily unavailable

**Use Cases:**
1. **Cost safety margins**: Set fallback higher than typical rates to avoid budget surprises
2. **Internal accounting**: Align fallback with organization's average LLM costs
3. **Development environments**: Set low fallback for test/dev models

**Monitoring Fallback Usage:**

Check which models are using fallback pricing:
```bash
# Get cost analytics and look for "FALLBACK" in cost breakdown
curl -X GET http://localhost:5050/api/v1/costs/analytics \
  -H "Authorization: Bearer $JWT" | jq '.cost_by_model.FALLBACK'
```

**Error Responses:**

| Status Code | Description | Example Response |
|-------------|-------------|------------------|
| 400 | Missing required fields | `{"status": "error", "message": "input_cost and output_cost are required"}` |
| 500 | Update failed | `{"status": "error", "message": "Failed to update fallback cost"}` |

---

#### 3.18.7. Get Cost Analytics

**Endpoint:** `GET /api/v1/costs/analytics`

**Authentication:** Admin only

**Description:** Retrieves comprehensive cost analytics across all sessions, including total costs, breakdowns by provider/model, trends over time, and most expensive queries.

**Response (200 OK):**
```json
{
  "total_cost": 247.83,
  "cost_by_provider": {
    "Google": 142.50,
    "Anthropic": 85.33,
    "OpenAI": 15.00,
    "FALLBACK": 5.00
  },
  "cost_by_model": {
    "gemini-2.0-flash-001": 98.40,
    "claude-opus-4-6": 75.20,
    "gemini-2.0-flash-thinking-exp": 44.10,
    "claude-sonnet-4-5": 10.13,
    "gpt-4o": 15.00,
    "FALLBACK": 5.00
  },
  "avg_cost_per_session": 2.48,
  "avg_cost_per_turn": 0.31,
  "most_expensive_sessions": [
    {
      "session_id": "abc123",
      "profile_tag": "FOCUS",
      "total_cost": 12.45,
      "turn_count": 8,
      "created_at": "2026-02-05T10:30:00Z"
    },
    {
      "session_id": "def456",
      "profile_tag": "CHAT",
      "total_cost": 8.92,
      "turn_count": 15,
      "created_at": "2026-02-04T14:20:00Z"
    }
  ],
  "most_expensive_queries": [
    {
      "session_id": "abc123",
      "turn_index": 3,
      "query_preview": "Analyze all customer transactions for...",
      "cost": 3.24,
      "provider": "Anthropic",
      "model": "claude-opus-4-6",
      "timestamp": "2026-02-05T10:45:00Z"
    }
  ],
  "cost_trend": [
    {
      "date": "2026-02-01",
      "total_cost": 45.20,
      "session_count": 12
    },
    {
      "date": "2026-02-02",
      "total_cost": 52.30,
      "session_count": 15
    }
  ]
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `total_cost` | float | Total cost across all sessions (USD) |
| `cost_by_provider` | object | Cost breakdown by LLM provider |
| `cost_by_model` | object | Cost breakdown by specific model |
| `avg_cost_per_session` | float | Average cost per session |
| `avg_cost_per_turn` | float | Average cost per turn (single query/response) |
| `most_expensive_sessions` | array | Top 10 sessions by total cost |
| `most_expensive_queries` | array | Top 10 individual queries by cost |
| `cost_trend` | array | Daily cost aggregation (last 30 days) |

**Example:**
```bash
curl -X GET http://localhost:5050/api/v1/costs/analytics \
  -H "Authorization: Bearer $JWT"
```

**Analytics Calculations:**

**Cost Formula:**
```
cost = (input_tokens / 1,000,000) * input_cost_per_million +
       (output_tokens / 1,000,000) * output_cost_per_million
```

**Session Cost:**
- Sum of all turn costs in the session
- Includes both strategic planning and tactical execution tokens

**Provider/Model Attribution:**
- Uses provider/model from LLM handler response metadata
- Falls back to profile's LLM config if metadata unavailable
- "FALLBACK" category shows costs from unknown models

**Use Cases:**
1. **Budget monitoring**: Track total LLM spending over time
2. **Cost optimization**: Identify expensive queries/sessions for optimization
3. **Provider comparison**: Compare costs across different LLM providers
4. **Financial reporting**: Generate cost reports for accounting/management

**Performance Note:**

Analytics endpoint scans all session workflow files on disk:
- First request may take 5-10 seconds for large deployments (1000+ sessions)
- Results are cached for 5 minutes
- Use `GET /api/v1/consumption/summary` for faster per-user consumption (database-backed)

**Relationship to Consumption Tracking:**

| Endpoint | Data Source | Scope | Performance |
|----------|-------------|-------|-------------|
| `/v1/costs/analytics` | Session files on disk | All sessions (deep analysis) | Slower (file I/O) |
| `/v1/consumption/summary` | Database (`consumption_records`) | Per-user aggregated | Faster (indexed queries) |

---

**Cost Management System Architecture:**

1. **Cost Database (`llm_model_costs` table)**:
   - Stores pricing for all LLM providers/models
   - Synced from LiteLLM + manual overrides
   - Fallback entry for unknown models

2. **LiteLLM Integration**:
   - Automatic pricing sync via `POST /v1/costs/sync`
   - Preserves manual overrides during sync
   - Checks model availability via provider APIs

3. **Cost Calculation Pipeline**:
   ```
   LLM Response → Extract Tokens → Lookup Pricing → Calculate Cost → Store in Consumption Records
   ```

4. **Consumption Records (`consumption_records` table)**:
   - Stores per-turn token/cost data
   - Indexed by user_uuid, timestamp, provider
   - Powers consumption analytics and quota enforcement

5. **Analytics Aggregation**:
   - Real-time: Session files (workflow.json)
   - Pre-aggregated: Database consumption records
   - Hybrid: Cost analytics uses both sources

**Cost Tracking Flow:**

```
1. User submits query
2. LLM handler calls provider API
3. Provider returns response with usage_metadata
4. Extract input_tokens, output_tokens
5. Lookup pricing: cost_manager.get_cost(provider, model)
6. Calculate cost: (tokens / 1M) * cost_per_million
7. Store in consumption_records table
8. Update session workflow.json
9. Emit token_update event to frontend
```

**Manual Override Workflow:**

```
1. Admin identifies incorrect pricing
2. POST /v1/costs/models (add new entry) OR
   PUT /v1/costs/models/{id} (update existing)
3. Entry marked as is_manual_override: true
4. Future syncs preserve this entry
5. Cost calculations use manual pricing
6. To revert: DELETE entry + POST /v1/costs/sync
```

---

### 3.19. Genie Multi-Profile Coordination

Manage Genie profiles that coordinate multiple child profiles to answer complex multi-domain questions. Genie profiles route queries to specialized expert profiles and synthesize their responses.

**Genie Architecture Overview:**

```
User Query → Genie Coordinator (Parent Session)
                ↓
     ┌──────────┼──────────┐
     ↓          ↓           ↓
Child Profile 1  Child Profile 2  Child Profile 3
(SQL Expert)    (Doc Search)     (API Expert)
     ↓          ↓           ↓
   Result 1   Result 2    Result 3
     └──────────┼──────────┘
                ↓
         Synthesized Answer
```

**Key Concepts:**

1. **Parent Session**: Genie profile that orchestrates coordination
2. **Child Sessions** (Slaves): Individual expert profiles invoked by Genie
3. **Primary Classification Profile**: Shared MCP server classification for child inheritance
4. **Coordination Flow**: Query → Route to experts → Collect results → Synthesize response

---

#### 3.19.1. Get Primary Classification Profile

**Endpoint:** `GET /api/v1/config/master-classification-profile`

**Authentication:** Required (JWT or Access Token)

**Description:** Retrieves the primary classification profile configuration. Returns per-server primary profile mappings (each MCP server can have its own primary profile) and legacy single-master profile for backwards compatibility.

**Primary Classification Profile Purpose:**

- **Inheritance**: Child profiles can inherit tool/prompt classification from primary profile
- **Consistency**: Ensures all child profiles use the same MCP server resources
- **Per-Server Flexibility**: Different MCP servers can have different primary profiles
- **Classification Propagation**: Disabled tools/prompts in primary automatically disabled in children

**Response (200 OK):**
```json
{
  "status": "success",
  "master_classification_profile_ids": {
    "postgres-mcp-server": "profile-123-abc",
    "mysql-mcp-server": "profile-456-def"
  },
  "master_classification_profile_id": "profile-123-abc"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `master_classification_profile_ids` | object | Dictionary mapping MCP server IDs to primary profile IDs |
| `master_classification_profile_id` | string | **DEPRECATED**: Legacy single primary profile (for backwards compatibility) |

**Example:**
```bash
curl -X GET http://localhost:5050/api/v1/config/master-classification-profile \
  -H "Authorization: Bearer $JWT"
```

**Per-Server Primary Profiles:**

Each MCP server can have its own primary profile:
- **postgres-mcp-server** → Uses SQL Expert profile as primary
- **mysql-mcp-server** → Uses different SQL profile as primary
- **docs-search-server** → Uses Documentation Expert as primary

**Use Cases:**
1. **Genie setup verification**: Check which profiles are set as primary before creating Genie
2. **Child profile configuration**: Determine which primary to inherit from
3. **Multi-server environments**: Manage different primary profiles per data source

**Migration Note:**

The `master_classification_profile_id` field is **deprecated** but maintained for backwards compatibility:
- **Old behavior** (single master): All child profiles inherited from one global primary
- **New behavior** (per-server): Each MCP server has its own primary profile
- **Migration path**: Update clients to use `master_classification_profile_ids` dictionary
- **Removal target**: Q2 2026

---

#### 3.19.2. Set Primary Classification Profile

**Endpoint:** `PUT /api/v1/config/master-classification-profile`

**Authentication:** Required (JWT or Access Token)

**Description:** Sets a profile as the primary classification profile for a specific MCP server. The primary profile must be `tool_enabled` type (not `llm_only`) and have an MCP server configured.

**Validation Rules:**

1. **Profile Type**: Must be `tool_enabled` (uses MCP tools)
2. **MCP Server**: Profile must have `mcpServerId` configured
3. **Not LLM-Only**: Cannot use `llm_only` or `rag_focused` profiles
4. **Profile Exists**: Profile must belong to the authenticated user

**Request Body:**
```json
{
  "profile_id": "profile-123-abc"
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `profile_id` | string | Yes | Profile ID to set as primary classification profile |

**Response (200 OK):**
```json
{
  "status": "success",
  "message": "Primary classification profile set successfully"
}
```

**Response (400 Bad Request - Validation Failure):**
```json
{
  "status": "error",
  "message": "Profile must be tool_enabled type with an MCP server configured"
}
```

**Example:**
```bash
curl -X PUT http://localhost:5050/api/v1/config/master-classification-profile \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"profile_id": "profile-123-abc"}'
```

**Side Effects:**

When primary classification profile is changed:

1. **Active Profile Inheritance Update**: If currently active profile inherits classification, `APP_STATE` is updated immediately
2. **Disabled Tools/Prompts Recalculation**: Child profiles re-inherit from new primary
3. **Resource Panel Refresh**: Frontend resource panel shows updated enabled/disabled state
4. **Context Regeneration**: MCP contexts regenerated to reflect new classification

**Example Workflow:**

```bash
# 1. Get current primary profile
CURRENT=$(curl -s -X GET http://localhost:5050/api/v1/config/master-classification-profile \
  -H "Authorization: Bearer $JWT" | jq -r '.master_classification_profile_id')

echo "Current primary: $CURRENT"

# 2. Set new primary profile
curl -X PUT http://localhost:5050/api/v1/config/master-classification-profile \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"profile_id": "profile-456-def"}'

# 3. Verify change
NEW=$(curl -s -X GET http://localhost:5050/api/v1/config/master-classification-profile \
  -H "Authorization: Bearer $JWT" | jq -r '.master_classification_profile_id')

echo "New primary: $NEW"
```

**Use Cases:**
1. **Genie coordinator setup**: Set SQL Expert as primary before creating SQL-focused Genie
2. **Environment switching**: Change primary when switching between dev/staging/prod data sources
3. **Resource access control**: Change primary to enable/disable specific MCP tools for all children

**Error Responses:**

| Status Code | Description | Example Response |
|-------------|-------------|------------------|
| 400 | Profile validation failed | `{"status": "error", "message": "Profile must be tool_enabled type"}` |
| 401 | Not authenticated | `{"status": "error", "message": "Authentication required"}` |
| 404 | Profile not found | `{"status": "error", "message": "Profile not found"}` |

---

#### 3.19.3. Execute Genie Coordinated Query

**Endpoint:** `POST /api/v1/sessions/{session_id}/genie-query`

**Authentication:** Required (JWT or Access Token)

**Description:** Submits a query to a Genie coordinator profile, which routes the question to multiple child profiles, collects their results, and synthesizes a comprehensive answer. This is the primary execution endpoint for Genie multi-profile coordination.

**Genie Execution Flow:**

```
1. User submits query to Genie parent session
2. Coordinator LLM analyzes query complexity
3. Determine which child profiles to invoke (routing)
4. Create child sessions (one per selected child profile)
5. Submit query to each child session via REST API
6. Poll child sessions for completion
7. Collect all child results
8. Coordinator synthesizes final answer
9. Return synthesized response to user
```

**Request Body:**
```json
{
  "prompt": "What are the top 3 products by revenue and what do customers say about them in reviews?"
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | Yes | User query to be routed to child profiles |

**Response (202 Accepted):**
```json
{
  "task_id": "task_20260206_103045_abc123",
  "status": "processing",
  "message": "Genie coordination started"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Unique task identifier for polling via `GET /api/v1/tasks/{task_id}` |
| `status` | string | Task status: `processing` (initial), `completed`, `error` |
| `message` | string | Human-readable status message |

**Example:**
```bash
# Submit query to Genie session
TASK_RESPONSE=$(curl -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/genie-query \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What are the top products and customer sentiment?"}')

TASK_ID=$(echo "$TASK_RESPONSE" | jq -r '.task_id')
echo "Task ID: $TASK_ID"

# Poll for results
sleep 5
curl -X GET "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $JWT"
```

**Genie Coordination Events:**

During execution, the task emits real-time events via the notification channel:

| Event Type | Description | Payload |
|------------|-------------|---------|
| `genie_coordination_start` | Coordination begins | `{"child_profile_count": 3}` |
| `genie_routing_decision` | Child profiles selected | `{"selected_profiles": ["SQL Expert", "Review Analyzer"]}` |
| `genie_child_session_created` | Child session spawned | `{"child_session_id": "...", "profile_tag": "SQL"}` |
| `genie_child_query_submitted` | Query sent to child | `{"child_session_id": "...", "child_task_id": "..."}` |
| `genie_child_result_received` | Child completed | `{"child_session_id": "...", "success": true}` |
| `genie_synthesis_start` | Synthesizing results | `{"result_count": 2}` |
| `genie_coordination_complete` | Final answer ready | `{"total_duration": 12.4}` |

**Poll Results:**

```bash
# Get full task results with events
curl -X GET "http://localhost:5050/api/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $JWT" | jq '{
    status: .status,
    events: .events | map(select(.event_type | startswith("genie_"))),
    result: .result
  }'
```

**Genie Configuration Requirements:**

Before using this endpoint, ensure the Genie profile has:

1. **Profile Type**: `profile_type: "genie"`
2. **Child Profiles**: `genieConfig.slaveProfiles: [...]` (at least 1 child)
3. **LLM Config**: `llmConfigurationId` for coordinator LLM
4. **Child Validation**: All child profiles must exist and be accessible

**Error Responses:**

| Status Code | Description | Example Response |
|-------------|-------------|------------------|
| 400 | Not a Genie profile | `{"error": "This endpoint is only for genie profiles. Use /v1/sessions/{session_id}/query for other profile types."}` |
| 400 | No child profiles configured | `{"error": "Genie profile has no child profiles configured."}` |
| 400 | Missing prompt | `{"error": "The 'prompt' field is required."}` |
| 401 | Not authenticated | `{"error": "Authentication required"}` |
| 404 | Session not found | `{"error": "Session 'abc123' not found."}` |

**Use Cases:**
1. **Multi-domain questions**: Questions requiring SQL + document search + API calls
2. **Complex analysis**: Combine data retrieval with sentiment analysis
3. **Cross-functional queries**: Route parts of query to different specialized profiles

**Routing Strategies:**

Genie coordinator can use different routing strategies:

| Strategy | Description | When to Use |
|----------|-------------|-------------|
| **Consult All** | Query all child profiles | Comprehensive analysis needed |
| **Smart Routing** | LLM selects relevant children | Efficiency over completeness |
| **Sequential** | Children run in order | Dependencies between profiles |
| **Parallel** | Children run simultaneously | No dependencies, fastest execution |

The routing strategy is configured in `genieConfig.routingStrategy` (profile configuration).

---

#### 3.19.4. Get Child Sessions

**Endpoint:** `GET /api/v1/sessions/{session_id}/slaves`

**Authentication:** Required (JWT or Access Token)

**Description:** Retrieves all child sessions spawned by a Genie parent session. Returns metadata about each child including profile, status, and nesting level.

**Response (200 OK):**
```json
{
  "parent_session_id": "session-genie-parent-abc123",
  "slave_count": 3,
  "slaves": [
    {
      "session_id": "session-child-sql-expert-def456",
      "slave_profile_id": "profile-sql-expert-123",
      "slave_profile_tag": "SQL_EXPERT",
      "nesting_level": 1,
      "created_at": "2026-02-06T10:30:15Z",
      "status": "active"
    },
    {
      "session_id": "session-child-doc-search-ghi789",
      "slave_profile_id": "profile-doc-search-456",
      "slave_profile_tag": "DOC_SEARCH",
      "nesting_level": 1,
      "created_at": "2026-02-06T10:30:18Z",
      "status": "active"
    },
    {
      "session_id": "session-child-api-expert-jkl012",
      "slave_profile_id": "profile-api-expert-789",
      "slave_profile_tag": "API_EXPERT",
      "nesting_level": 1,
      "created_at": "2026-02-06T10:30:20Z",
      "status": "active"
    }
  ]
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `parent_session_id` | string | Genie parent session ID (echoed from request) |
| `slave_count` | integer | Number of child sessions spawned |
| `slaves` | array | List of child session objects |
| `slaves[].session_id` | string | Child session unique identifier |
| `slaves[].slave_profile_id` | string | Profile ID used for this child |
| `slaves[].slave_profile_tag` | string | Profile tag (e.g., "SQL_EXPERT") |
| `slaves[].nesting_level` | integer | Nesting depth (1 = direct child, 2 = grandchild, etc.) |
| `slaves[].created_at` | string (ISO 8601) | Child session creation timestamp |
| `slaves[].status` | string | Session status: `active`, `archived` |

**Example:**
```bash
# Get all child sessions for a Genie parent
curl -X GET http://localhost:5050/api/v1/sessions/$GENIE_SESSION_ID/slaves \
  -H "Authorization: Bearer $JWT" | jq '.slaves[] | {profile_tag, status}'
```

**Nesting Levels:**

Genie profiles can spawn nested child sessions:

```
Level 0: User Session (regular profile)
Level 1: Genie Parent Session
Level 2: Child Session (SQL Expert)
Level 3: Grandchild Session (if Child is also a Genie)
```

**Use Cases:**
1. **Coordination tracking**: Monitor which child profiles were invoked
2. **Result aggregation**: Fetch individual child session results
3. **Debugging**: Inspect child session execution details
4. **Session cleanup**: Identify orphaned child sessions for archival

**Example: Fetch Child Session Details**

```bash
# Get child sessions
CHILDREN=$(curl -s -X GET http://localhost:5050/api/v1/sessions/$GENIE_SESSION_ID/slaves \
  -H "Authorization: Bearer $JWT")

# Extract first child session ID
CHILD_ID=$(echo "$CHILDREN" | jq -r '.slaves[0].session_id')

# Get full child session data
curl -X GET http://localhost:5050/api/v1/sessions/$CHILD_ID \
  -H "Authorization: Bearer $JWT" | jq '{
    session_id,
    profile_tag,
    turn_count,
    is_genie_slave: .genie_metadata.is_genie_slave,
    parent_session_id: .genie_metadata.parent_session_id
  }'
```

**Error Responses:**

| Status Code | Description | Example Response |
|-------------|-------------|------------------|
| 401 | Not authenticated | `{"error": "Authentication required"}` |
| 404 | Parent session not found | `{"error": "Session 'abc123' not found."}` |
| 500 | Database error | `{"error": "Failed to retrieve child sessions."}` |

**Child Session Lifecycle:**

1. **Creation**: Child session created when Genie routes query to child profile
2. **Execution**: Child runs independently with its own profile configuration
3. **Completion**: Results stored in child session's conversation.json
4. **Aggregation**: Parent Genie synthesizes child results
5. **Persistence**: Child sessions remain accessible for inspection

**Session Archiving:**

Child sessions are automatically archived when:
- Parent Genie session is deleted
- Child profile is deleted (cascade archiving)
- MCP server used by child profile is removed

---

#### 3.19.5. Get Parent Genie Session

**Endpoint:** `GET /api/v1/sessions/{session_id}/genie-parent`

**Authentication:** Required (JWT or Access Token)

**Description:** For a given session, determines if it's a child session and returns its parent Genie session information. Returns `null` if the session is not a child.

**Response (200 OK - Child Session):**
```json
{
  "is_genie_slave": true,
  "parent_session_id": "session-genie-parent-abc123",
  "nesting_level": 1,
  "slave_profile_tag": "SQL_EXPERT",
  "parent_session": {
    "session_id": "session-genie-parent-abc123",
    "profile_id": "profile-genie-coordinator-xyz",
    "profile_tag": "GENIE_COORDINATOR",
    "created_at": "2026-02-06T10:30:00Z"
  }
}
```

**Response (200 OK - Not a Child Session):**
```json
{
  "is_genie_slave": false,
  "parent_session_id": null
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `is_genie_slave` | boolean | Whether this session is a child of a Genie parent |
| `parent_session_id` | string \| null | Parent Genie session ID (null if not a child) |
| `nesting_level` | integer | Nesting depth (0 = root, 1 = child, 2 = grandchild) |
| `slave_profile_tag` | string | Profile tag used for this child session |
| `parent_session` | object \| null | Parent session metadata |
| `parent_session.session_id` | string | Parent session unique identifier |
| `parent_session.profile_id` | string | Parent profile ID (Genie coordinator) |
| `parent_session.profile_tag` | string | Parent profile tag |
| `parent_session.created_at` | string (ISO 8601) | Parent session creation timestamp |

**Example:**
```bash
# Check if a session is a child
curl -X GET http://localhost:5050/api/v1/sessions/$SESSION_ID/genie-parent \
  -H "Authorization: Bearer $JWT" | jq '{
    is_child: .is_genie_slave,
    parent: .parent_session_id,
    nesting_level
  }'
```

**Use Cases:**
1. **Breadcrumb navigation**: Build session hierarchy for UI navigation
2. **Context understanding**: Determine if session results are child results
3. **Result aggregation**: Trace child results back to parent coordination
4. **Session visualization**: Render parent-child relationships in UI

**Example: Build Session Hierarchy**

```bash
# Recursive function to build full hierarchy
function get_hierarchy() {
  local SESSION_ID=$1

  # Get parent info
  PARENT_INFO=$(curl -s -X GET http://localhost:5050/api/v1/sessions/$SESSION_ID/genie-parent \
    -H "Authorization: Bearer $JWT")

  IS_CHILD=$(echo "$PARENT_INFO" | jq -r '.is_genie_slave')

  if [ "$IS_CHILD" == "true" ]; then
    PARENT_ID=$(echo "$PARENT_INFO" | jq -r '.parent_session_id')
    NESTING=$(echo "$PARENT_INFO" | jq -r '.nesting_level')

    echo "Session $SESSION_ID is child of $PARENT_ID (level $NESTING)"

    # Recurse to find grandparent
    get_hierarchy "$PARENT_ID"
  else
    echo "Session $SESSION_ID is root (no parent)"
  fi
}

# Start from a child session
get_hierarchy "session-child-sql-expert-def456"

# Output:
# Session session-child-sql-expert-def456 is child of session-genie-parent-abc123 (level 1)
# Session session-genie-parent-abc123 is root (no parent)
```

**Genie Metadata Structure:**

Child sessions store parent relationship in `genie_metadata`:

```json
{
  "genie_metadata": {
    "is_genie_slave": true,
    "parent_session_id": "session-genie-parent-abc123",
    "slave_profile_id": "profile-sql-expert-123",
    "created_by_genie": true
  }
}
```

**Error Responses:**

| Status Code | Description | Example Response |
|-------------|-------------|------------------|
| 401 | Not authenticated | `{"error": "Authentication required"}` |
| 404 | Session not found | `{"error": "Session 'abc123' not found."}` |

**UI Integration:**

Frontend can use this endpoint to:
- Show "Part of Genie Coordination" badge on child sessions
- Render breadcrumb: `Parent Genie → SQL Expert (this session)`
- Link child session back to parent for context
- Disable certain UI actions for child sessions (e.g., prevent deletion while parent is active)

---

**Genie System Architecture Overview:**

**Database Schema:**

1. **Profiles Table**: Stores Genie profile configuration
   ```sql
   profile_type: 'genie'
   genieConfig: {
     slaveProfiles: ['profile-id-1', 'profile-id-2'],
     routingStrategy: 'smart' | 'consult_all' | 'sequential',
     synthesisPrompt: 'Custom synthesis instructions...'
   }
   ```

2. **Genie Session Links Table**: Tracks parent-child relationships
   ```sql
   CREATE TABLE genie_session_links (
     parent_session_id TEXT,
     slave_session_id TEXT,
     slave_profile_id TEXT,
     slave_profile_tag TEXT,
     nesting_level INTEGER,
     created_at TEXT
   )
   ```

3. **Session Metadata**: `genie_metadata` field in session JSON
   ```json
   {
     "is_genie_slave": true,
     "parent_session_id": "...",
     "slave_profile_id": "...",
     "created_by_genie": true
   }
   ```

**Execution Flow:**

```
1. User calls POST /v1/sessions/{id}/genie-query
2. Validate session has genie profile type
3. Get child profiles from genieConfig.slaveProfiles
4. Create background task for coordination
5. Coordinator LLM analyzes query
6. Routing decision (which children to invoke)
7. For each selected child:
   a. Create child session via session_manager
   b. Submit query to child via POST /v1/sessions/{child_id}/query
   c. Poll child task for completion
8. Collect all child results
9. Coordinator synthesizes final answer
10. Store result in parent session
11. Emit genie_coordination_complete event
```

**Best Practices:**

1. **Profile Design**: Create focused child profiles (SQL Expert, Document Search, API Expert)
2. **Primary Classification**: Set appropriate primary profile before creating Genie
3. **LLM Selection**: Use powerful LLM for coordinator (Claude Opus, GPT-4) for better routing
4. **Child Limits**: Limit to 3-5 child profiles to avoid coordination overhead
5. **Synthesis Prompts**: Customize synthesis instructions in `genieConfig.synthesisPrompt`

**Performance Considerations:**

| Metric | Value | Notes |
|--------|-------|-------|
| Child session creation | ~500ms | Database write + metadata setup |
| Child query submission | ~50ms | REST API call overhead |
| Child execution time | Variable | Depends on profile type (SQL vs LLM-only) |
| Synthesis time | ~2-5s | Coordinator LLM processes all results |
| Total coordination time | 10-30s | For 3 children running in parallel |

**Troubleshooting:**

**Issue: Genie query returns 400 "Not a genie profile"**
- **Cause**: Session's profile is not type `genie`
- **Fix**: Create session with a Genie profile, or use regular query endpoint

**Issue: Child sessions not appearing in `/slaves` endpoint**
- **Cause**: Coordination hasn't started or failed early
- **Fix**: Check task status via `GET /api/v1/tasks/{task_id}` for errors

**Issue: Child results empty or incomplete**
- **Cause**: Child profile misconfigured or MCP tools unavailable
- **Fix**: Test child profile independently, verify MCP server connectivity

**Issue: Synthesis produces generic response**
- **Cause**: Coordinator LLM insufficient for synthesis complexity
- **Fix**: Upgrade to more powerful LLM (e.g., Claude Opus), or customize synthesis prompt

---

### 3.20. Extension Management

Manage post-processing extensions — list, activate, deactivate, scaffold, and edit.

#### List All Extensions

```bash
curl -X GET http://localhost:5050/api/v1/extensions \
  -H "Authorization: Bearer $JWT"
```

**Response:**
```json
{
  "extensions": [
    {
      "extension_id": "json",
      "display_name": "JSON Formatter",
      "description": "Formats LLM answers as structured JSON",
      "extension_tier": "standard",
      "requires_llm": false,
      "output_target": "chat_append",
      "version": "1.0.0",
      "category": "Formatting",
      "is_builtin": true
    }
  ]
}
```

#### List Activated Extensions

```bash
curl -X GET http://localhost:5050/api/v1/extensions/activated \
  -H "Authorization: Bearer $JWT"
```

#### Activate Extension

```bash
curl -X POST http://localhost:5050/api/v1/extensions/json/activate \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"default_param": "minimal"}'
```

#### Deactivate Extension

```bash
curl -X POST http://localhost:5050/api/v1/extensions/activations/json/deactivate \
  -H "Authorization: Bearer $JWT"
```

#### Delete Activation

```bash
curl -X DELETE http://localhost:5050/api/v1/extensions/activations/json2 \
  -H "Authorization: Bearer $JWT"
```

#### Update Activation Config

```bash
curl -X PUT http://localhost:5050/api/v1/extensions/activations/json/config \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"default_param": "full"}'
```

#### Rename Activation

```bash
curl -X PUT http://localhost:5050/api/v1/extensions/activations/json2/rename \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"new_name": "json_full"}'
```

#### Get Extension Source Code

```bash
curl -X GET http://localhost:5050/api/v1/extensions/json/source \
  -H "Authorization: Bearer $JWT"
```

**Response:**
```json
{
  "name": "json",
  "source": "# Python source code...",
  "manifest": { "extension_tier": "standard", ... }
}
```

#### Save Extension Source Code

Saves edited source code for user extensions (under `~/.tda/extensions/`). Built-in extensions return `403`.

```bash
curl -X PUT http://localhost:5050/api/v1/extensions/my_ext/source \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"source": "EXTENSION_NAME = \"my_ext\"\n\ndef transform(answer_text, param=None):\n    return {\"length\": len(answer_text)}\n"}'
```

**Response:**
```json
{
  "status": "success",
  "name": "my_ext",
  "loaded": true
}
```

#### Scaffold Extension (Create from Template)

Creates a new extension skeleton and writes it to `~/.tda/extensions/`.

```bash
curl -X POST http://localhost:5050/api/v1/extensions/scaffold \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "my_ext", "level": "convention", "description": "Custom extension"}'
```

| Level | Files Created |
|-------|--------------|
| `convention` | `~/.tda/extensions/my_ext.py` |
| `simple` | `~/.tda/extensions/my_ext/my_ext.py` |
| `standard` | `~/.tda/extensions/my_ext/my_ext.py` + `manifest.json` |
| `llm` | `~/.tda/extensions/my_ext/my_ext.py` + `manifest.json` |

**Response:**
```json
{
  "status": "success",
  "path": "/Users/you/.tda/extensions/my_ext.py",
  "files": ["my_ext.py"],
  "level": "convention",
  "loaded": true
}
```

#### Preview Scaffold (Without Writing)

Returns generated file contents without writing to disk.

```bash
curl -X POST http://localhost:5050/api/v1/extensions/scaffold/preview \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "my_ext", "level": "simple", "description": "Preview test"}'
```

**Response:**
```json
{
  "status": "success",
  "path": "/Users/you/.tda/extensions/my_ext",
  "files": {
    "my_ext.py": "\"\"\"\\n#my_ext extension — Preview test\\n..."
  },
  "level": "simple"
}
```

#### Reload Extensions

Hot-reload all extensions from disk.

```bash
curl -X POST http://localhost:5050/api/v1/extensions/reload \
  -H "Authorization: Bearer $JWT"
```

#### Export Extension

Export an extension as a downloadable `.extension` ZIP file. Works for both built-in and user-created extensions.

```bash
curl -X POST http://localhost:5050/api/v1/extensions/json/export \
  -H "Authorization: Bearer $JWT" \
  --output json.extension
```

**Response:** Binary ZIP file download containing `manifest.json` + `source.py`.

The manifest includes `export_format_version` and `exported_at` metadata. Internal fields (`_is_user`, `_source_path`, etc.) are stripped.

#### Import Extension

Import an extension from an uploaded `.extension` or `.zip` file.

```bash
curl -X POST http://localhost:5050/api/v1/extensions/import \
  -H "Authorization: Bearer $JWT" \
  -F "file=@my_ext.extension"
```

**Response:**
```json
{
  "status": "success",
  "extension_id": "my_ext",
  "name": "My Extension",
  "message": "Extension 'my_ext' imported successfully."
}
```

**Notes:**
- ZIP must contain `source.py` and optionally `manifest.json`
- Extension ID is sanitized (alphanumeric + underscore only)
- Returns `403` if admin has disabled custom extension creation

#### Duplicate Extension

Duplicate any extension (built-in or user-created) into a new user extension.

```bash
curl -X POST http://localhost:5050/api/v1/extensions/json/duplicate \
  -H "Authorization: Bearer $JWT"
```

**Response (201):**
```json
{
  "status": "success",
  "extension_id": "json_copy",
  "display_name": "JSON Output (Copy)",
  "message": "Extension duplicated as \"json_copy\"."
}
```

**Notes:**
- Generates unique ID: `{id}_copy`, `{id}_copy_2`, etc.
- Rewrites name references in Python source
- Returns `403` if admin has disabled custom extension creation
- Returns `404` if source extension not found

#### Delete Extension

Delete a user-created extension. Built-in extensions cannot be deleted.

```bash
curl -X DELETE http://localhost:5050/api/v1/extensions/my_ext \
  -H "Authorization: Bearer $JWT"
```

**Response:**
```json
{
  "status": "deleted",
  "extension_id": "my_ext"
}
```

**Error responses:**

| Status | Condition | Body |
|--------|-----------|------|
| `403` | Built-in extension | `{"error": "Built-in extensions cannot be deleted"}` |
| `409` | Has active activations | `{"error": "Extension has active activations. Deactivate them first."}` |
| `404` | Extension not found | `{"error": "Extension 'xyz' not found"}` |

**Notes:**
- Only user-created extensions can be deleted
- All activations must be deactivated before deletion
- Inactive activation rows are cleaned up automatically

---

### 3.21. Skill Management

Skills are pre-processing prompt injections that modify LLM behavior before query execution. The skill system supports discovery, activation, creation, import/export, and a marketplace for sharing skills across users.

**Authentication Required:** All endpoints require JWT authentication.

**Skill Format:** Claude Code compatible — each skill is a `skill.json` manifest + `<name>.md` content file. An optional `uderia` section in the manifest provides platform-specific features (params, injection target).

---

#### 3.21.1. List Available Skills

**Endpoint:** `GET /v1/skills`

**Purpose:** List all available skills (built-in + user-created), filtered by admin governance settings.

**Success Response:**
```json
{
  "skills": [
    {
      "skill_id": "sql-expert",
      "name": "SQL Expert",
      "description": "SQL best practices and optimization guidance",
      "is_builtin": true,
      "injection_target": "system_prompt",
      "tags": ["sql", "database", "best-practices"],
      "allowed_params": ["strict", "lenient"],
      "keywords": ["sql", "query"]
    }
  ],
  "_settings": {
    "user_skills_enabled": true,
    "user_skills_marketplace_enabled": true,
    "skills_mode": "all"
  }
}
```

---

#### 3.21.2. Reload Skills from Disk

**Endpoint:** `POST /v1/skills/reload`

**Purpose:** Hot-reload skills from the filesystem (picks up new/modified skill files).

**Success Response:**
```json
{
  "status": "success",
  "message": "Skills reloaded",
  "count": 8
}
```

---

#### 3.21.3. Get Skill Content

**Endpoint:** `GET /v1/skills/{skill_id}/content`

**Purpose:** Get full skill content and manifest for the editor.

**Success Response:**
```json
{
  "skill_id": "sql-expert",
  "content": "# SQL Expert\n\nYou are an SQL optimization expert...",
  "manifest": {
    "name": "sql-expert",
    "version": "1.0.0",
    "description": "SQL best practices",
    "tags": ["sql", "database"],
    "main_file": "sql-expert.md",
    "uderia": {
      "allowed_params": ["strict", "lenient"],
      "injection_target": "system_prompt"
    }
  }
}
```

---

#### 3.21.4. Create/Update User Skill

**Endpoint:** `PUT /v1/skills/{skill_id}`

**Request Body:**
```json
{
  "content": "# My Skill\n\nSkill instructions here...",
  "manifest": {
    "name": "my-skill",
    "description": "Custom skill description",
    "tags": ["custom"],
    "version": "1.0.0"
  }
}
```

**Success Response:**
```json
{
  "status": "success",
  "skill_id": "my-skill",
  "message": "Skill saved"
}
```

---

#### 3.21.5. Delete User Skill

**Endpoint:** `DELETE /v1/skills/{skill_id}`

**Purpose:** Delete a user-created skill from disk (built-in skills cannot be deleted).

**Success Response:**
```json
{
  "status": "success",
  "message": "Skill deleted"
}
```

---

#### 3.21.6. Export Skill

**Endpoint:** `POST /v1/skills/{skill_id}/export`

**Purpose:** Export a skill as a `.skill` file (ZIP containing `skill.json` + `<name>.md`).

**Response:** Binary `.skill` file download.

**Response Headers:**
```
Content-Type: application/zip
Content-Disposition: attachment; filename="sql-expert.skill"
```

---

#### 3.21.7. Import Skill

**Endpoint:** `POST /v1/skills/import`

**Purpose:** Import a skill from a `.skill` or `.zip` file.

**Request:** `multipart/form-data` with `file` field.

**Success Response:**
```json
{
  "status": "success",
  "skill_id": "imported-skill",
  "message": "Skill imported: imported-skill"
}
```

---

#### 3.21.8. List Activated Skills

**Endpoint:** `GET /v1/skills/activated`

**Purpose:** Get the current user's activated skills (for `!` autocomplete).

**Success Response:**
```json
{
  "skills": [
    {
      "skill_id": "sql-expert",
      "activation_name": "sql-expert",
      "is_active": true,
      "default_param": "strict"
    }
  ]
}
```

---

#### 3.21.9. Activate Skill

**Endpoint:** `POST /v1/skills/{skill_id}/activate`

**Request Body:**
```json
{
  "activation_name": "my-sql"
}
```

**Success Response:**
```json
{
  "status": "success",
  "activation_name": "my-sql"
}
```

---

#### 3.21.10. Deactivate Skill

**Endpoint:** `POST /v1/skills/activations/{name}/deactivate`

**Purpose:** Soft-deactivate a skill (sets `is_active=0`).

---

#### 3.21.11. Publish Skill to Marketplace

**Endpoint:** `POST /v1/skills/{skill_id}/publish`

**Purpose:** Publish a user-created skill to the marketplace for sharing.

**Prerequisites:**
- Skill must be user-created (not built-in)
- Marketplace must be enabled (`user_skills_marketplace_enabled = true`)

**Request Body:**
```json
{
  "visibility": "public",
  "targeted_user_ids": []
}
```

**Parameters:**
- `visibility` (string, optional) — `public` (default) or `targeted`
- `targeted_user_ids` (array, optional) — For targeted visibility, list of user UUIDs

**Success Response:**
```json
{
  "status": "success",
  "marketplace_id": "a1b2c3d4-...",
  "message": "Skill 'my-skill' published to marketplace"
}
```

**Error Responses:**
| Code | Condition | Example |
|------|-----------|---------|
| `400` | Skill is built-in | `{"error": "Only user-created skills can be published"}` |
| `403` | Marketplace disabled | `{"error": "Skill marketplace is not enabled"}` |
| `409` | Already published | `{"error": "Skill already published by you"}` |
| `404` | Skill not found | `{"error": "Skill not found"}` |

---

#### 3.21.12. Browse Marketplace Skills

**Endpoint:** `GET /v1/marketplace/skills`

**Purpose:** Browse published skills in the marketplace with search, sort, filter, and pagination.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Page number |
| `per_page` | integer | 20 | Results per page (max 100) |
| `search` | string | — | Search name, description, tags |
| `sort_by` | string | `recent` | Sort: `recent`, `rating`, `installs`, `downloads`, `name` |
| `injection_target` | string | — | Filter: `system_prompt` or `user_context` |

**Success Response:**
```json
{
  "skills": [
    {
      "id": "a1b2c3d4-...",
      "skill_id": "my-skill",
      "name": "My Skill",
      "description": "A useful skill",
      "version": "1.0.0",
      "author": "admin",
      "injection_target": "system_prompt",
      "has_params": false,
      "tags_json": "[\"sql\", \"database\"]",
      "publisher_username": "admin",
      "visibility": "public",
      "average_rating": 4.5,
      "rating_count": 12,
      "install_count": 45,
      "download_count": 0,
      "published_at": "2026-02-22T10:00:00",
      "is_publisher": false
    }
  ],
  "page": 1,
  "per_page": 20,
  "total_count": 1,
  "total_pages": 1
}
```

---

#### 3.21.13. Get Marketplace Skill Detail

**Endpoint:** `GET /v1/marketplace/skills/{marketplace_id}`

**Purpose:** Get detailed information about a marketplace skill including ratings and manifest.

**Success Response:**
```json
{
  "skill": {
    "id": "a1b2c3d4-...",
    "skill_id": "my-skill",
    "name": "My Skill",
    "description": "A useful skill",
    "version": "1.0.0",
    "author": "admin",
    "injection_target": "system_prompt",
    "has_params": false,
    "tags_json": "[\"sql\"]",
    "manifest_json": "{...}",
    "publisher_username": "admin",
    "average_rating": 4.5,
    "rating_count": 12,
    "install_count": 45,
    "download_count": 0,
    "published_at": "2026-02-22T10:00:00",
    "user_rating": 5,
    "user_comment": "Excellent!"
  }
}
```

---

#### 3.21.14. Install Skill from Marketplace

**Endpoint:** `POST /v1/marketplace/skills/{marketplace_id}/install`

**Purpose:** Install a marketplace skill to the local skills directory.

**Behavior:**
1. Reads `skill.json` + `.md` from marketplace storage
2. Saves to `~/.tda/skills/{skill_id}/` via skill manager
3. Hot-reloads skill manager
4. Increments install count

**Success Response:**
```json
{
  "status": "success",
  "skill_id": "my-skill",
  "message": "Skill 'My Skill' installed from marketplace"
}
```

**Error Responses:**
| Code | Condition | Example |
|------|-----------|---------|
| `403` | Marketplace disabled | `{"error": "Skill marketplace is not enabled"}` |
| `404` | Not found | `{"error": "Marketplace skill not found"}` |

---

#### 3.21.15. Rate Marketplace Skill

**Endpoint:** `POST /v1/marketplace/skills/{marketplace_id}/rate`

**Purpose:** Submit a 1-5 star rating with optional comment for a marketplace skill.

**Request Body:**
```json
{
  "rating": 5,
  "comment": "Excellent skill, very useful!"
}
```

**Parameters:**
- `rating` (integer, required) — 1 to 5
- `comment` (string, optional) — Review text

**Success Response:**
```json
{
  "status": "success",
  "message": "Rating submitted"
}
```

**Error Responses:**
| Code | Condition | Example |
|------|-----------|---------|
| `400` | Invalid rating | `{"error": "Rating must be between 1 and 5"}` |
| `400` | Self-rating | `{"error": "Cannot rate your own skill"}` |
| `403` | Marketplace disabled | `{"error": "Skill marketplace is not enabled"}` |
| `404` | Not found | `{"error": "Marketplace skill not found"}` |

---

#### 3.21.16. Unpublish Skill from Marketplace

**Endpoint:** `DELETE /v1/marketplace/skills/{marketplace_id}`

**Purpose:** Remove a skill from the marketplace (publisher only). Does not affect users who already installed it.

**Success Response:**
```json
{
  "status": "success",
  "message": "Skill unpublished from marketplace"
}
```

**Error Responses:**
| Code | Condition | Example |
|------|-----------|---------|
| `403` | Not the publisher | `{"error": "Only the publisher can unpublish"}` |
| `404` | Not found | `{"error": "Marketplace skill not found"}` |

---

#### 3.21.17. Admin Skill Settings

**Endpoint:** `GET /v1/admin/skill-settings`

**Purpose:** Get governance settings including marketplace enabled flag.

**Success Response:**
```json
{
  "settings": {
    "skills_mode": "all",
    "disabled_skills": "[]",
    "user_skills_enabled": "true",
    "auto_skills_enabled": "false",
    "user_skills_marketplace_enabled": "true"
  },
  "builtin_skills": [...]
}
```

**Endpoint:** `POST /v1/admin/skill-settings`

**Purpose:** Update governance settings.

**Request Body:**
```json
{
  "user_skills_enabled": true,
  "user_skills_marketplace_enabled": false
}
```

---

### 3.22. Admin Endpoints

Admin-only endpoints for system management and maintenance operations.

**Authentication Required:**
- All endpoints require admin-level authentication (JWT with admin role)
- Non-admin users receive `403 Forbidden`

**Available Endpoints:**
- Clear Prompt Cache

---

#### 3.22.1. Clear Prompt Cache

**Endpoint:** `POST /v1/admin/prompts/clear-cache`

**Purpose:** Invalidate the in-memory PromptLoader cache to force reloading of system prompts from the database. Used after deploying prompt updates via external scripts (e.g., `update_prompt.py`).

**Authentication:** Admin JWT required

**Request:**
```bash
# Get admin JWT token
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}' | jq -r '.token')

# Clear cache
curl -X POST http://localhost:5050/api/v1/admin/prompts/clear-cache \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json"
```

**Response (Success):**
```json
{
  "success": true,
  "message": "Prompt cache cleared successfully"
}
```

**Response (Error):**
```json
{
  "success": false,
  "error": "Failed to clear prompt cache: [error details]"
}
```

**Status Codes:**
- `200 OK` - Cache cleared successfully
- `401 Unauthorized` - Missing or invalid JWT token
- `403 Forbidden` - User is not an admin
- `500 Internal Server Error` - Cache clearing failed

**Use Cases:**

1. **After Prompt Updates**: When deploying updated system prompts via `update_prompt.py`, call this endpoint to ensure changes take effect immediately without restarting the application.

2. **Development/Testing**: Clear cache to test prompt changes during development.

3. **Troubleshooting**: Force reload of prompts if incorrect prompts are being served.

**Example Workflow (Prompt Deployment):**

```bash
# 1. Update prompts in database
cd /path/to/trusted-data-agent-license
python update_prompt.py --app-root /path/to/uderia --all

# 2. Clear cache (done automatically by update_prompt.py, but can be manual)
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

curl -X POST http://localhost:5050/api/v1/admin/prompts/clear-cache \
  -H "Authorization: Bearer $JWT"

# 3. Verify new prompts are in use
# Submit a query and check logs for "Using prompt: [prompt_name]"
```

**Technical Details:**

The PromptLoader maintains three in-memory caches:
- `_prompt_cache`: Loaded prompts with resolved parameters
- `_parameter_cache`: Global and prompt-specific parameters
- `_override_cache`: User/profile-level prompt overrides

This endpoint calls `PromptLoader.clear_cache()` which empties all three caches, forcing fresh reads from the database on next prompt access.

**Performance Impact:**
- Cache clearing is instant (~1ms)
- Next prompt access will be slower (~50-100ms) as it reads from database
- Subsequent accesses resume normal cached speed (~1ms)

**Security Considerations:**
- Only admin users can clear cache (prevents unauthorized cache manipulation)
- Cache clearing does not modify database (read-only operation)
- No risk of data loss or corruption

**Monitoring:**

Check application logs for confirmation:
```
INFO - PromptLoader cache cleared by admin request
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
            f"{self.base_url}/api/v1/auth/register",
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
            f"{self.base_url}/api/v1/auth/login",
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
            `${this.baseURL}/api/v1/auth/register`,
            { username, email, password }
        );
        return response.data;
    }
    
    async login(username, password) {
        try {
            const response = await axios.post(
                `${this.baseURL}/api/v1/auth/login`,
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
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
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
| `/api/v1/auth/register` | 3 requests | 1 hour per IP |
| `/api/v1/auth/login` | 5 requests | 1 minute per IP |
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
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login and get JWT |
| POST | `/api/v1/auth/logout` | Logout (web UI) |
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

**Last Updated:** February 22, 2026
**API Version:** v1
**Document Version:** 2.2.0