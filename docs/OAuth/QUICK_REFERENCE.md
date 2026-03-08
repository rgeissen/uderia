# OAuth Implementation - Quick Reference

Complete quick reference for the full 4-phase OAuth implementation.

## Project Structure

```
src/trusted_data_agent/auth/
├── oauth_config.py              # Phase 1: Provider configuration
├── oauth_handlers.py            # Phase 2: OAuth flow handling
├── oauth_middleware.py          # Phase 2: Quart integration
├── email_verification.py        # Phase 4: Email verification
├── account_merge.py             # Phase 4: Account merging
├── oauth_rate_limiter.py        # Phase 4: Rate limiting & abuse detection
├── oauth_audit_logger.py        # Phase 4: Audit logging & analytics
└── models.py                    # Updated with OAuth models

api/
└── auth_routes.py               # OAuth API endpoints

static/js/
├── oauth.js                     # Phase 3: OAuth client
└── connected-accounts.js        # Phase 3: Account management UI

templates/
└── login.html                   # Phase 3: OAuth buttons

docs/OAuth/
├── SETUP_GUIDE.md              # Provider setup instructions
├── INTEGRATION_GUIDE.md        # Developer reference
└── PHASE_4_SECURITY_POLISH.md  # Security features
```

## Database Models

### Phase 1-2: Core Models
```python
User                    # Enhanced with OAuth fields
OAuthAccount           # OAuth account links
AuthToken              # Session tokens
```

### Phase 4: Security Models
```python
EmailVerificationToken # Email verification
AuditLog               # Audit logging (existing)
```

## API Endpoints

### Authentication & OAuth
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/auth/login` | POST | ❌ | Username/password login |
| `/api/v1/auth/logout` | POST | ✅ | Logout |
| `/api/v1/auth/register` | POST | ❌ | User registration |
| `/api/v1/auth/refresh` | POST | ✅ | Refresh token |

### OAuth Endpoints
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/auth/oauth/providers` | GET | ❌ | List providers |
| `/api/v1/auth/oauth/<provider>` | GET | ❌ | Initiate login |
| `/api/v1/auth/oauth/<provider>/callback` | GET | ❌ | Handle callback |
| `/api/v1/auth/oauth/<provider>/link` | GET | ✅ | Link account |
| `/api/v1/auth/oauth/<provider>/link/callback` | GET | ✅ | Handle link |
| `/api/v1/auth/oauth/<provider>/disconnect` | POST | ✅ | Unlink account |
| `/api/v1/auth/oauth/accounts` | GET | ✅ | List linked accounts |

## Core Classes & Methods

### Phase 1: Configuration
```python
OAuthProvider
  - is_configured() -> bool
  
OAuthConfig
  - get_callback_url(provider) -> str
  - validate() -> bool
```

### Phase 2: OAuth Flow
```python
OAuthHandler
  - exchange_code_for_token(code, redirect_uri) -> token_dict
  - get_user_info(access_token) -> user_info
  - handle_callback(code, redirect_uri) -> (jwt_token, user_dict)
  - _sync_user_and_generate_token() -> (jwt_token, user_dict)

OAuthSession
  - generate_state(provider) -> state
  - verify_state(state, provider) -> (valid, return_to)

OAuthAuthorizationBuilder
  - build_authorization_url(provider) -> auth_url
  - build_authorization_url_for_linking(provider) -> auth_url

OAuthCallbackValidator
  - validate_callback_request(provider) -> (valid, code, state, error)

OAuthErrorHandler
  - handle_oauth_error(message) -> error_dict
  - log_oauth_event(provider, event_type, success)
```

### Phase 3: Frontend
```javascript
AuthClient
  - setToken(token)           // Process OAuth token
  - isAuthenticated() -> bool
  - getToken() -> string
  - setSession(token, user)

OAuthClient
  - getAvailableProviders() -> providers
  - getLinkedAccounts() -> accounts
  - initiateOAuthLink(provider)
  - disconnectOAuthAccount(provider) -> {success, message}
  - handleOAuthCallback() -> {success, token, error}

ConnectedAccountsComponent
  - initialize()
  - render()
  - refresh()
```

### Phase 4: Security
```python
EmailVerificationService
  - generate_verification_token(user_id, email) -> token
  - verify_email(token, email) -> (success, user_id)
  - is_email_verified(user_id, email) -> bool
  - get_pending_verification(user_id) -> token
  - clean_expired_tokens()

EmailVerificationValidator
  - is_valid_email_domain(email) -> bool
  - should_verify_email(provider, is_verified) -> bool

AccountMergeService
  - find_existing_user_by_email(email) -> user
  - can_merge_oauth_to_user(user_id, provider, provider_id) -> (can, reason)
  - merge_oauth_account(...) -> (success, message)
  - suggest_account_merge(provider, email) -> user
  - get_merge_candidates(user_id) -> candidates

OAuthRateLimiter
  - check_oauth_login_limit(ip, provider) -> (allowed, attempts)
  - check_oauth_link_limit(user_id, provider) -> (allowed, attempts)
  - record_oauth_attempt(operation, provider, id, success)

OAuthAbuseDetector
  - detect_brute_force(ip, provider) -> bool
  - detect_account_enumeration(ip, provider) -> bool
  - detect_rapid_account_linking(user_id) -> bool

OAuthAuditLogger
  - log_oauth_login(provider, user_id, ip)
  - log_oauth_link(provider, user_id, success)
  - log_email_verification(user_id, email, success)
  - log_suspicious_activity(type, provider, details)

OAuthAnalytics
  - get_oauth_stats(days) -> stats_dict
  - get_provider_popularity() -> dict
```

## Configuration

### Environment Variables (.env)

```env
# OAuth Settings
OAUTH_HTTPS_ONLY=True|False
OAUTH_INSECURE_TRANSPORT=False
OAUTH_CALLBACK_URL=https://domain.com/api/v1/auth/oauth/{provider}/callback

# Providers
OAUTH_GOOGLE_CLIENT_ID=xxx
OAUTH_GOOGLE_CLIENT_SECRET=xxx
OAUTH_GITHUB_CLIENT_ID=xxx
OAUTH_GITHUB_CLIENT_SECRET=xxx
# ... more providers

# Security
OAUTH_EMAIL_VERIFICATION_REQUIRED=True
OAUTH_RATE_LIMIT_LOGIN=20
OAUTH_BLOCK_THROWAWAY_EMAILS=True
```

## Common Usage Examples

### Frontend: OAuth Login
```javascript
// Login page loads providers
const oauth = new OAuthClient();
const providers = await oauth.getAvailableProviders();

// User clicks provider
window.location.href = `/api/v1/auth/oauth/google`;

// After callback
const auth = new AuthClient();
auth.setToken(tokenFromURL);
```

### Frontend: Link Account
```javascript
const oauth = new OAuthClient();
oauth.initiateOAuthLink('github');

// Component auto-handles UI
const component = new ConnectedAccountsComponent();
await component.initialize();
```

### Backend: Complete OAuth
```python
from trusted_data_agent.auth.oauth_handlers import OAuthHandler

handler = OAuthHandler('google')
jwt_token, user = await handler.handle_callback(code, redirect_uri)

if jwt_token:
    # Successful login, return token to frontend
    return {'token': jwt_token}
```

### Backend: Check Rate Limit
```python
from trusted_data_agent.auth.oauth_rate_limiter import OAuthRateLimiter

allowed, attempts = OAuthRateLimiter.check_oauth_login_limit(ip_address, 'google')

if not allowed:
    return {'error': 'Too many attempts, try again later'}, 429
```

### Backend: Get Analytics
```python
from trusted_data_agent.auth.oauth_audit_logger import OAuthAnalytics

stats = OAuthAnalytics.get_oauth_stats(days=7)
popularity = OAuthAnalytics.get_provider_popularity()
```

## Testing Checklist

### Phase 1: Configuration ✅
- [ ] Providers load from environment
- [ ] Invalid providers return None
- [ ] Callback URLs format correctly

### Phase 2: OAuth Flow ✅
- [ ] Redirect to provider works
- [ ] Callback validation works
- [ ] Token exchange succeeds
- [ ] User info fetched correctly
- [ ] JWT token generated
- [ ] User created/updated

### Phase 3: Frontend ✅
- [ ] OAuth buttons display
- [ ] Click button redirects correctly
- [ ] Token received in callback
- [ ] Session stored
- [ ] User logged in

### Phase 4: Security ✅
- [ ] Email verification sent
- [ ] Account merging works
- [ ] Rate limiting blocks after limit
- [ ] Brute force detected
- [ ] Audit logs created
- [ ] Analytics calculated

## Deployment Checklist

- [ ] Environment variables configured (.env)
- [ ] Database migrations run
- [ ] Email delivery configured (for verification)
- [ ] HTTPS enabled (OAUTH_HTTPS_ONLY=True)
- [ ] Rate limits tuned for your load
- [ ] Audit log retention policy set
- [ ] Monitoring/alerting configured
- [ ] Backup strategy in place

## Performance Considerations

| Operation | Performance | Notes |
|-----------|------------|-------|
| OAuth login | 500-1000ms | Network dependent |
| Token exchange | 200-500ms | Provider dependent |
| User info fetch | 100-300ms | Includes profile data |
| Email verification | <50ms | Local database |
| Rate limit check | <1ms | In-memory lookup |
| Account merge | 10-50ms | Database transaction |

**Optimization Tips:**
- Cache provider configs
- Use Redis for distributed rate limiting
- Batch audit log writes
- Implement database connection pooling

## Security Checklist

- [ ] HTTPS required in production
- [ ] OAuth secrets in environment variables
- [ ] Rate limiting enabled
- [ ] Email verification for new users
- [ ] Throwaway emails blocked
- [ ] CSRF state validation
- [ ] Brute force detection active
- [ ] Audit logging enabled
- [ ] Session timeout configured
- [ ] Secure cookies enabled

## Troubleshooting Quick Links

| Issue | Solution |
|-------|----------|
| "Provider not configured" | Check .env file, restart app |
| "Invalid redirect_uri" | Verify registered URIs in provider |
| "State parameter mismatch" | Clear cookies, try again |
| "Email verification stuck" | Check token expiry, resend |
| "Rate limit exceeded" | Wait 1 hour, check IP not blocked |
| "Account merge failed" | Email must match, no duplicate OAuth |

## Files Changed in Complete Implementation

### New Files
- `src/trusted_data_agent/auth/oauth_config.py`
- `src/trusted_data_agent/auth/oauth_handlers.py`
- `src/trusted_data_agent/auth/oauth_middleware.py`
- `src/trusted_data_agent/auth/email_verification.py`
- `src/trusted_data_agent/auth/account_merge.py`
- `src/trusted_data_agent/auth/oauth_rate_limiter.py`
- `src/trusted_data_agent/auth/oauth_audit_logger.py`
- `static/js/oauth.js`
- `static/js/connected-accounts.js`
- `docs/OAuth/SETUP_GUIDE.md`
- `docs/OAuth/INTEGRATION_GUIDE.md`
- `docs/OAuth/PHASE_4_SECURITY_POLISH.md`

### Modified Files
- `requirements.txt` - Added authlib, httpx
- `src/trusted_data_agent/auth/models.py` - Added OAuth models
- `src/trusted_data_agent/auth/security.py` - Added imports
- `src/trusted_data_agent/api/auth_routes.py` - Added OAuth routes
- `static/js/auth.js` - Added setToken() method
- `templates/login.html` - Added OAuth buttons

## Resources

- [Authlib Documentation](https://docs.authlib.org/)
- [OAuth 2.0 Spec](https://tools.ietf.org/html/rfc6749)
- [OpenID Connect](https://openid.net/connect/)
- [OWASP OAuth Security](https://owasp.org/www-community/attacks/oauth-security)

## Support & Questions

For issues or questions:
1. Check relevant guide in `docs/OAuth/`
2. Review code comments and docstrings
3. Check audit logs for errors
4. Enable debug logging for troubleshooting

