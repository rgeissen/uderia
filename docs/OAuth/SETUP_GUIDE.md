# OAuth Setup Guide

This guide provides step-by-step instructions for configuring OAuth providers with Uderia.

## Table of Contents

1. [Overview](#overview)
2. [Google OAuth Setup](#google-oauth-setup)
3. [GitHub OAuth Setup](#github-oauth-setup)
4. [Microsoft OAuth Setup](#microsoft-oauth-setup)
5. [Discord OAuth Setup](#discord-oauth-setup)
6. [Okta OAuth Setup](#okta-oauth-setup)
7. [Configuration](#configuration)
8. [Testing](#testing)
9. [Troubleshooting](#troubleshooting)

---

## Overview

OAuth enables users to sign in using existing accounts from various providers, eliminating the need to create new credentials. Uderia supports:

- **Google** - Most common, reliable
- **GitHub** - Great for developer audiences
- **Microsoft** - Enterprise SSO via Azure AD
- **Discord** - Community-focused applications
- **Okta** - Enterprise OIDC provider

### Key Benefits

✅ Streamlined login experience  
✅ Reduced password management  
✅ Social profile integration  
✅ Enterprise SSO support  
✅ Automatic account creation  

---

## Google OAuth Setup

### 1. Create Google Cloud Project

1. Visit [Google Cloud Console](https://console.cloud.google.com)
2. Click "Select a Project" → "New Project"
3. Enter project name (e.g., "Uderia")
4. Click "Create"

### 2. Enable Google+ API

1. In the search bar, type "Google+ API"
2. Click the result
3. Click "Enable"

### 3. Create OAuth Credentials

1. Go to **APIs & Services** → **Credentials** (left sidebar)
2. Click **Create Credentials** → **OAuth client ID**
3. Choose **Web application**
4. Set Application name (e.g., "Uderia Login")

### 4. Configure Redirect URIs

In the "Authorized redirect URIs" section, add:

```
http://localhost:8000/api/v1/auth/oauth/google/callback    (development)
https://yourdomain.com/api/v1/auth/oauth/google/callback   (production)
```

### 5. Copy Credentials

1. After creation, you'll see your credentials
2. Copy the **Client ID** and **Client Secret**
3. Add to your `.env` file:

```env
OAUTH_GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
OAUTH_GOOGLE_CLIENT_SECRET=your_client_secret
```

---

## GitHub OAuth Setup

### 1. Access GitHub Settings

1. Go to [GitHub Developer Settings](https://github.com/settings/developers)
2. Click **OAuth Apps** (or **New OAuth App**)

### 2. Register New OAuth Application

Fill in the form:

| Field | Value |
|-------|-------|
| **Application name** | Uderia |
| **Homepage URL** | https://yourdomain.com (or http://localhost:8000) |
| **Authorization callback URL** | https://yourdomain.com/api/v1/auth/oauth/github/callback |

### 3. Copy Credentials

After registration:

1. Copy **Client ID**
2. Click "Generate a new client secret" and copy it
3. Add to `.env`:

```env
OAUTH_GITHUB_CLIENT_ID=your_client_id
OAUTH_GITHUB_CLIENT_SECRET=your_client_secret
```

### 4. Verify Redirect URI

For local development, you can update the Redirect URI to:
```
http://localhost:8000/api/v1/auth/oauth/github/callback
```

---

## Microsoft OAuth Setup (Azure AD)

### 1. Create Azure AD Application

1. Go to [Azure Portal](https://portal.azure.com)
2. Search for **Azure Active Directory**
3. Click **App registrations** (left sidebar)
4. Click **+ New registration**

### 2. Register Application

Fill in:

| Field | Value |
|-------|-------|
| **Name** | Uderia |
| **Supported account types** | Accounts in any organizational directory and personal Microsoft accounts |
| **Redirect URI** | Web - https://yourdomain.com/api/v1/auth/oauth/microsoft/callback |

### 3. Add Redirect URI (if needed)

1. Go to **Authentication** (left sidebar)
2. Under "Redirect URIs", add:
   ```
   http://localhost:8000/api/v1/auth/oauth/microsoft/callback    (dev)
   https://yourdomain.com/api/v1/auth/oauth/microsoft/callback   (prod)
   ```

### 4. Create Client Secret

1. Go to **Certificates & secrets** (left sidebar)
2. Click **+ New client secret**
3. Set expiration (recommend 12 months)
4. Copy the secret **immediately** (you won't see it again)

### 5. Copy Application Credentials

1. Go back to **Overview**
2. Copy **Application (client) ID**
3. Add to `.env`:

```env
OAUTH_MICROSOFT_CLIENT_ID=your_client_id
OAUTH_MICROSOFT_CLIENT_SECRET=your_client_secret
```

---

## Discord OAuth Setup

### 1. Create Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**
3. Enter name "Uderia"
4. Click **Create**

### 2. Configure OAuth2

1. Go to **OAuth2** → **General** (left sidebar)
2. Copy **Client ID**
3. Under "CLIENT SECRET", click "Reset Secret" and copy it

### 3. Add Redirect URI

1. Go to **OAuth2** → **Redirects**
2. Click **Add Redirect**
3. Add redirect URIs:
   ```
   http://localhost:8000/api/v1/auth/oauth/discord/callback    (dev)
   https://yourdomain.com/api/v1/auth/oauth/discord/callback   (prod)
   ```
4. Click **Save Changes**

### 4. Update .env

```env
OAUTH_DISCORD_CLIENT_ID=your_client_id
OAUTH_DISCORD_CLIENT_SECRET=your_client_secret
```

---

## Okta OAuth Setup

### 1. Sign Up for Okta

1. Go to [Okta Developer](https://developer.okta.com)
2. Sign up for free developer account

### 2. Create OAuth Application

1. Go to **Applications** → **Applications** (left sidebar)
2. Click **Create App Integration**
3. Choose **OIDC - OpenID Connect** and **Web Application**
4. Click **Next**

### 3. Configure Application

Fill in:

| Field | Value |
|-------|-------|
| **App integration name** | Uderia |
| **Sign-in redirect URIs** | https://yourdomain.com/api/v1/auth/oauth/okta/callback |
| **Sign-out redirect URIs** | https://yourdomain.com/login |
| **Controlled access** | Public |

### 4. Copy Credentials

After creation:

1. Copy **Client ID**
2. Copy **Client secret**
3. Get your **Okta domain** from the top-right corner (e.g., `https://dev-12345.okta.com`)

### 5. Update .env

```env
OKTA_DOMAIN=https://dev-12345.okta.com
OAUTH_OKTA_CLIENT_ID=your_client_id
OAUTH_OKTA_CLIENT_SECRET=your_client_secret
```

---

## Configuration

### 1. Create Environment File

Copy the template:

```bash
cp .env.oauth.template .env
```

### 2. Fill in Your Credentials

Edit `.env` and add the credentials for each provider you want to enable:

```env
# Enable only the providers you've set up
OAUTH_GOOGLE_CLIENT_ID=xxx
OAUTH_GOOGLE_CLIENT_SECRET=xxx
# OAUTH_GITHUB_CLIENT_ID=xxx  # Commented out if not configured
# OAUTH_GITHUB_CLIENT_SECRET=xxx
```

### 3. Configure Callback URL

Update the callback URL to match your deployment:

```env
# For local development
OAUTH_CALLBACK_URL=http://localhost:8000/api/v1/auth/oauth/{provider}/callback

# For production (HTTPS required)
OAUTH_CALLBACK_URL=https://yourdomain.com/api/v1/auth/oauth/{provider}/callback
```

### 4. Verify Security Settings

For production, ensure:

```env
OAUTH_HTTPS_ONLY=True
OAUTH_INSECURE_TRANSPORT=False
OAUTH_SESSION_COOKIE_SECURE=True
```

For development only:

```env
OAUTH_HTTPS_ONLY=False
OAUTH_INSECURE_TRANSPORT=True  # Only if using HTTP
```

---

## Testing

### 1. Start Application

```bash
python src/trusted_data_agent/main.py
```

### 2. Test OAuth Login

1. Open http://localhost:8000/login
2. Click an OAuth provider button
3. You should be redirected to the provider's login page
4. After login, you should be redirected back and logged in

### 3. Test Account Linking

1. Log in with username/password
2. Go to Profile → Connected Accounts
3. Click "Link" on an OAuth provider
4. Complete the OAuth flow
5. Account should appear in the linked accounts list

### 4. Test Account Unlinking

1. In Connected Accounts, click "Disconnect"
2. Confirm the action
3. Account should be removed from the list

---

## Troubleshooting

### "Provider not configured" Error

**Cause:** OAuth provider credentials are missing from `.env`

**Solution:**
1. Check that the provider is configured in `.env`
2. Verify spelling of environment variable names
3. Restart the application after changing `.env`

### "Invalid redirect_uri" Error

**Cause:** Redirect URI doesn't match what's registered with the provider

**Solution:**
1. Check registered redirect URIs in provider's dashboard
2. Ensure `OAUTH_CALLBACK_URL` in `.env` matches exactly
3. For development, use `http://localhost:8000`; for production, use `https://yourdomain.com`

### OAuth Login Creates Duplicate Accounts

**Cause:** User logs in with both OAuth and username/password

**Solution:**
1. This is expected behavior - use the same email for both methods
2. Future releases will auto-merge accounts with matching emails

### "State parameter mismatch" Error

**Cause:** Session was lost or state validation failed

**Solution:**
1. Ensure cookies are enabled in your browser
2. Don't open callback URL directly - use the OAuth button
3. Clear browser cookies and try again

### Provider says "localhost not allowed"

**Cause:** For production providers, localhost isn't whitelisted

**Solution:**
1. For testing, create a development app registration in the provider
2. Use your machine's IP address or local domain
3. Add `/etc/hosts` entry: `127.0.0.1 uderia.local`
4. Use `http://uderia.local:8000` as callback URL

### "HTTPS required" Error

**Cause:** Trying to use OAuth in production without HTTPS

**Solution:**
1. Set `OAUTH_HTTPS_ONLY=False` only in development
2. In production, use HTTPS and set `OAUTH_HTTPS_ONLY=True`
3. Update callback URL to use `https://`

---

## Additional Resources

- [Authlib Documentation](https://docs.authlib.org/)
- [OAuth 2.0 Specification](https://tools.ietf.org/html/rfc6749)
- [OpenID Connect](https://openid.net/connect/)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review provider-specific documentation
3. Enable debug logging in `main.py`
4. Check application logs in `logs/` directory
