# OAuth Integration Guide for Developers

Quick reference for integrating OAuth into Uderia components.

## Frontend Integration

### 1. Adding OAuth to a Page

Include the required scripts:

```html
<!-- OAuth client library -->
<script src="/static/js/oauth.js"></script>

<!-- Connected accounts component (optional) -->
<script src="/static/js/connected-accounts.js"></script>
```

### 2. Using OAuthClient Class

```javascript
const oauth = new OAuthClient();

// Get available providers
const providers = await oauth.getAvailableProviders();

// Initiate OAuth login flow
oauth.initiateOAuthLogin('google');  // Redirects to Google login

// Get user's linked accounts
const accounts = await oauth.getLinkedAccounts();

// Link OAuth account (requires authentication)
oauth.initiateOAuthLink('github');

// Disconnect OAuth account
const result = await oauth.disconnectOAuthAccount('github');
if (result.success) {
    console.log('Account disconnected');
}
```

### 3. Embedding Connected Accounts Component

```html
<!-- In your profile/settings page -->
<div id="connected-accounts-container"></div>

<script src="/static/js/connected-accounts.js"></script>
```

The component will automatically initialize and handle all OAuth account management.

### 4. Handling OAuth Callback

The callback is handled automatically by `login.html`. For custom pages:

```javascript
const oauth = new OAuthClient();

// Check for token in URL
const result = await oauth.handleOAuthCallback();

if (result.success) {
    // Store token using AuthClient
    const auth = new AuthClient();
    auth.setToken(result.token);
    // Redirect user
    window.location.href = '/';
} else {
    // Show error
    console.error('OAuth callback failed:', result.error);
}
```

### 5. Displaying Provider Info

```javascript
const oauth = new OAuthClient();
const providerInfo = oauth.getProviderInfo();

// Get info for a specific provider
const googleInfo = providerInfo['google'];
console.log(googleInfo.name);      // "Google"
console.log(googleInfo.icon);      // "🔵"
console.log(googleInfo.color);     // "#EA4335"
```

---

## Backend Integration

### 1. OAuth Handler Usage

```python
from trusted_data_agent.auth.oauth_handlers import OAuthHandler

# Initialize handler for a provider
handler = OAuthHandler('google')

# Complete OAuth flow in callback handler
jwt_token, user_dict = await handler.handle_callback(
    code=authorization_code,
    redirect_uri=callback_url,
    state=state_param
)
```

### 2. Account Linking

```python
from trusted_data_agent.auth.oauth_handlers import (
    link_oauth_to_existing_user,
    unlink_oauth_from_user
)

# Link OAuth account to authenticated user
success, message = await link_oauth_to_existing_user(
    user_id=current_user.id,
    provider_name='github',
    code=authorization_code,
    redirect_uri=callback_url
)

# Unlink OAuth account
success, message = await unlink_oauth_from_user(
    user_id=current_user.id,
    provider_name='github'
)
```

### 3. OAuth Middleware

```python
from trusted_data_agent.auth.oauth_middleware import (
    OAuthAuthorizationBuilder,
    OAuthCallbackValidator,
    OAuthSession,
    get_client_ip
)

# Build authorization URL
auth_url = await OAuthAuthorizationBuilder.build_authorization_url(
    provider_name='google',
    return_to='/dashboard'
)

# Validate callback
is_valid, code, state, error = await OAuthCallbackValidator.validate_callback_request('google')

# CSRF protection via session
state = await OAuthSession.generate_state('google')
is_valid, return_to = await OAuthSession.verify_state(state, 'google')
```

### 4. OAuth Configuration

```python
from trusted_data_agent.auth.oauth_config import (
    get_provider,
    get_configured_providers,
    OAuthConfig
)

# Get a specific provider
provider = get_provider('google')

# Get all configured providers
configured = get_configured_providers()

# Validate configuration
OAuthConfig.validate()

# Get callback URL for provider
callback_url = OAuthConfig.get_callback_url('google')
```

### 5. API Routes

All OAuth routes are registered in `auth/api/auth_routes.py`:

```
GET    /api/v1/auth/oauth/providers              # List providers
GET    /api/v1/auth/oauth/<provider>             # Initiate OAuth
GET    /api/v1/auth/oauth/<provider>/callback    # Handle callback
GET    /api/v1/auth/oauth/<provider>/link        # Initiate linking
POST   /api/v1/auth/oauth/<provider>/disconnect  # Unlink account
GET    /api/v1/auth/oauth/accounts               # Get user's accounts
```

---

## Database Models

### User OAuth Fields

```python
# In User model
oauth_provider: str          # 'google', 'github', etc.
oauth_id: str               # Provider's unique ID
oauth_metadata: dict        # Provider-specific data
oauth_accounts: List[OAuthAccount]  # Relationship to OAuth accounts
```

### OAuthAccount Model

```python
class OAuthAccount(Base):
    user_id: str                    # Link to User
    provider: str                   # Provider name
    provider_user_id: str           # Provider's unique ID
    provider_email: str             # Email from provider
    provider_name: str              # Name from provider
    provider_picture_url: str       # Profile picture
    provider_metadata: dict         # Additional OAuth data
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime
```

---

## Configuration Options

### Environment Variables

```env
# OAuth Settings
OAUTH_HTTPS_ONLY=True|False              # Require HTTPS
OAUTH_INSECURE_TRANSPORT=True|False      # Allow HTTP (dev only)
OAUTH_CALLBACK_URL=<url>                 # Callback base URL

# Session Security
OAUTH_SESSION_COOKIE_SECURE=True|False   # Secure cookie flag
OAUTH_SESSION_COOKIE_HTTPONLY=True       # HttpOnly flag
OAUTH_SESSION_COOKIE_SAMESITE=Lax|Strict

# Provider Credentials
OAUTH_<PROVIDER>_CLIENT_ID=<id>
OAUTH_<PROVIDER>_CLIENT_SECRET=<secret>
```

### Supported Providers

- `google` - Google OAuth2
- `github` - GitHub OAuth2
- `microsoft` - Microsoft/Azure AD OAuth2
- `discord` - Discord OAuth2
- `okta` - Okta OIDC

---

## Error Handling

### Common Error Responses

```json
{
    "status": "error",
    "message": "OAuth provider not configured"
}
```

### Audit Logging

All OAuth events are automatically logged:

```python
# Logged automatically in oauth_middleware.py
# Access logs in database or logs/ directory
# Track: login, link, unlink, callback events
```

---

## Security Best Practices

✅ **Always use HTTPS in production** - Set `OAUTH_HTTPS_ONLY=True`

✅ **Validate state parameter** - Done automatically by `OAuthSession`

✅ **Protect client secrets** - Use environment variables, never commit to git

✅ **Use secure cookies** - `OAUTH_SESSION_COOKIE_SECURE=True`

✅ **CSRF protection** - State validation prevents CSRF attacks

✅ **Email verification** - Consider verifying email before allowing OAuth login

✅ **Rate limiting** - Implement rate limits on OAuth endpoints

✅ **Audit logging** - All OAuth events are logged for security monitoring

---

## Troubleshooting

### Issue: Token not stored after OAuth callback

**Check:**
1. Verify callback URL matches registered URI
2. Check browser cookies are enabled
3. Check for JavaScript errors in console

### Issue: "Provider not configured" error

**Check:**
1. Provider credentials in `.env`
2. Proper environment variable names (`OAUTH_<PROVIDER>_CLIENT_ID`)
3. Application restarted after `.env` changes

### Issue: OAuth button doesn't appear

**Check:**
1. `oauth.js` script is loaded
2. No JavaScript errors in console
3. Provider is configured in `.env`

### Issue: Account linking fails

**Check:**
1. User is authenticated
2. OAuth account not already linked to another user
3. Provider account has valid email

---

## Examples

### Complete Login Flow

```html
<!-- Login page with OAuth -->
<button onclick="initiateOAuthLogin('google')">Sign in with Google</button>

<script>
function initiateOAuthLogin(provider) {
    window.location.href = `/api/v1/auth/oauth/${provider}`;
}

// After redirect from OAuth callback
window.addEventListener('load', async () => {
    const auth = new AuthClient();
    const oauth = new OAuthClient();
    
    const result = await oauth.handleOAuthCallback();
    if (result.success) {
        auth.setToken(result.token);
        window.location.href = '/';
    }
});
</script>
```

### Account Management UI

```html
<!-- Profile page with account management -->
<div id="connected-accounts-container"></div>

<script src="/static/js/connected-accounts.js"></script>
<!-- Component auto-initializes and handles all interactions -->
```

### Custom OAuth Integration

```python
from trusted_data_agent.auth.oauth_handlers import OAuthHandler

@app.route('/custom-oauth-endpoint', methods=['GET'])
async def custom_oauth_handler():
    code = request.args.get('code')
    provider = 'google'
    
    handler = OAuthHandler(provider)
    jwt_token, user = await handler.handle_callback(
        code=code,
        redirect_uri='https://yourdomain.com/custom-oauth-endpoint'
    )
    
    return jsonify({
        'token': jwt_token,
        'user': user
    })
```

---

## Next Steps

1. ✅ Configure OAuth providers in `.env`
2. ✅ Test OAuth login at `/login`
3. ✅ Implement account linking in profile
4. ✅ Monitor OAuth events in audit logs
5. ✅ Consider email verification workflows
6. ✅ Set up rate limiting on OAuth endpoints

---

## Reference Documentation

- [Phase 1: Foundation Setup](./PHASE_1.md)
- [Phase 2: Authlib Integration](./PHASE_2.md)
- [OAuth Setup Guide](./SETUP_GUIDE.md)
- [API Reference](./API_REFERENCE.md)
