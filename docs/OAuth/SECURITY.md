# Phase 4: Security & Polish - OAuth Enhancement

Comprehensive security hardening, email verification, account management, and analytics for OAuth.

## Overview

Phase 4 adds critical security features and operational capabilities:

✅ **Email Verification** - Verify email ownership for OAuth signups  
✅ **Account Merging** - Automatically merge OAuth accounts with existing users sharing same email  
✅ **Rate Limiting** - Prevent abuse and brute force attacks  
✅ **Audit Logging** - Enhanced tracking for security monitoring  
✅ **Abuse Detection** - Identify suspicious activity patterns  
✅ **Analytics** - Track OAuth provider usage and trends  

---

## 1. Email Verification System

### Overview

Email verification ensures OAuth accounts are tied to legitimate email addresses and prevents unauthorized account creation.

### Features

**Auto-Verification for Trusted Providers:**
- Google, Microsoft: Email pre-verified by provider
- GitHub, Discord: Email verification required
- Okta: Email verification based on provider settings

**Verification Flow:**
1. User completes OAuth flow
2. System checks if email verification is needed
3. If needed, generates 24-hour verification token
4. User receives verification email (future implementation)
5. Email verified, account activated

### Implementation

**Models:**
```python
class EmailVerificationToken(Base):
    user_id: str
    email: str
    token_hash: str
    verification_type: str  # 'oauth', 'signup', 'email_change'
    oauth_provider: str
    expires_at: datetime
    verified_at: datetime
```

**Service Class:** `EmailVerificationService`

```python
from trusted_data_agent.auth.email_verification import EmailVerificationService

# Generate verification token
token = EmailVerificationService.generate_verification_token(
    user_id=user.id,
    email='user@example.com',
    verification_type='oauth',
    oauth_provider='google'
)

# Verify email
success, user_id = EmailVerificationService.verify_email(token, email)

# Check if email is verified
is_verified = EmailVerificationService.is_email_verified(user_id, email)

# Get pending verification
pending = EmailVerificationService.get_pending_verification(user_id)

# Clean up expired tokens
EmailVerificationService.clean_expired_tokens()
```

**Email Validation:**
```python
from trusted_data_agent.auth.email_verification import EmailVerificationValidator

# Check for throwaway email domains
is_valid = EmailVerificationValidator.is_valid_email_domain('user@tempmail.com')

# Determine if verification is required
needs_verification = EmailVerificationValidator.should_verify_email(
    oauth_provider='github',
    is_email_verified=False
)
```

### Configuration

Default settings (in `email_verification.py`):
- Token validity: 24 hours
- Throwaway domains blocked: tempmail, guerrillamail, mailinator, etc.
- Auto-verified providers: Google, Microsoft
- Requires verification: GitHub, Discord, Okta

### Database

New table: `email_verification_tokens`

```sql
CREATE TABLE email_verification_tokens (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL,
    verification_type VARCHAR(50),
    oauth_provider VARCHAR(50),
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL,
    verified_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

---

## 2. Account Merging & Deduplication

### Overview

Automatically merges OAuth accounts with existing users who share the same email address, preventing account duplication.

### Features

**Automatic Merging:**
- Detects existing users by email
- Links OAuth account to existing user
- Merges profile information
- Prevents duplicate accounts

**Merge Suggestions:**
- Suggests accounts that could be merged
- Lists potential merge candidates
- Manual merge approval workflow

**Safety Checks:**
- Prevents merging same OAuth to multiple users
- Validates email ownership
- Preserves user preferences

### Implementation

**Service Class:** `AccountMergeService`

```python
from trusted_data_agent.auth.account_merge import AccountMergeService

# Find existing user by email
user = AccountMergeService.find_existing_user_by_email('user@example.com')

# Check if merge is possible
can_merge, reason = AccountMergeService.can_merge_oauth_to_user(
    user_id='user-123',
    provider_name='github',
    provider_user_id='gh-12345'
)

# Perform account merge
success, message = AccountMergeService.merge_oauth_account(
    user_id='user-123',
    provider_name='github',
    provider_user_id='gh-12345',
    provider_email='user@example.com',
    provider_name_str='John Doe',
    provider_metadata={...}
)

# Suggest merge candidates
suggested = AccountMergeService.suggest_account_merge(
    oauth_provider='google',
    provider_email='user@example.com'
)

# Get merge candidates
candidates = AccountMergeService.get_merge_candidates(user_id='user-123')
```

### Database

Uses existing tables:
- `users` - Main user accounts
- `oauth_accounts` - OAuth account links

Merge checks for unique constraints:
```sql
UNIQUE (user_id, provider)
UNIQUE (provider, provider_user_id)
```

---

## 3. Rate Limiting

### Overview

Prevents abuse of OAuth endpoints through rate limiting on:
- OAuth login attempts
- Account linking attempts
- Callback processing
- Email verification attempts

### Configuration

**Default Limits (per hour):**
- OAuth login: 20 attempts per IP
- Account linking: 10 attempts per user
- Callback processing: 50 attempts per IP

### Implementation

**Service Class:** `OAuthRateLimiter`

```python
from trusted_data_agent.auth.oauth_rate_limiter import OAuthRateLimiter

# Check login limit
allowed, attempts = OAuthRateLimiter.check_oauth_login_limit(
    ip_address='192.168.1.1',
    provider='google'
)

# Check link limit
allowed, attempts = OAuthRateLimiter.check_oauth_link_limit(
    user_id='user-123',
    provider='github'
)

# Record attempt
OAuthRateLimiter.record_oauth_attempt(
    operation='login',
    provider='google',
    identifier='192.168.1.1',
    success=True
)
```

**Abuse Detector:** `OAuthAbuseDetector`

```python
from trusted_data_agent.auth.oauth_rate_limiter import OAuthAbuseDetector

# Detect brute force
is_brute_force = OAuthAbuseDetector.detect_brute_force(
    ip_address='192.168.1.1',
    provider='google',
    failed_attempts=5
)

# Detect rapid account linking
is_rapid = OAuthAbuseDetector.detect_rapid_account_linking(
    user_id='user-123',
    provider_count=5
)
```

### Implementation Notes

- **In-Memory Storage**: Default implementation uses in-memory dict
- **Production**: Use Redis for distributed rate limiting
- **Cleanup**: Automatic cleanup every hour
- **Custom Limits**: Configurable per provider/operation

---

## 4. Enhanced Audit Logging

### Overview

Comprehensive audit logging for all OAuth operations, enabling security monitoring and analytics.

### Logged Events

| Event | Details |
|-------|---------|
| `oauth_initiate` | OAuth flow started |
| `oauth_callback` | Provider callback received |
| `oauth_login` | Successful user login |
| `oauth_link` | Account link created |
| `oauth_unlink` | Account unlinked |
| `oauth_merge` | Accounts merged |
| `email_verification` | Email verified |
| `rate_limit_exceeded` | Rate limit triggered |
| `suspicious_activity` | Abuse detected |

### Implementation

**Logger Class:** `OAuthAuditLogger`

```python
from trusted_data_agent.auth.oauth_audit_logger import OAuthAuditLogger

# Log login
OAuthAuditLogger.log_oauth_login(
    provider='google',
    user_id='user-123',
    ip_address='192.168.1.1',
    is_new_user=False
)

# Log account link
OAuthAuditLogger.log_oauth_link(
    provider='github',
    user_id='user-123',
    success=True
)

# Log suspicious activity
OAuthAuditLogger.log_suspicious_activity(
    activity_type='brute_force',
    provider='google',
    ip_address='192.168.1.1',
    details={'failed_attempts': 5}
)

# Log email verification
OAuthAuditLogger.log_email_verification(
    user_id='user-123',
    email='user@example.com',
    verification_type='oauth',
    success=True
)
```

**Analytics Class:** `OAuthAnalytics`

```python
from trusted_data_agent.auth.oauth_audit_logger import OAuthAnalytics

# Get stats
stats = OAuthAnalytics.get_oauth_stats(days=7)
# Returns: {
#   'total_events': 150,
#   'successful_logins': 45,
#   'failed_logins': 5,
#   'unique_users': 30,
#   'by_provider': {'google': {'success': 30}, ...}
# }

# Get provider popularity
popularity = OAuthAnalytics.get_provider_popularity()
# Returns: {'google': 45, 'github': 30, 'microsoft': 15}
```

### Database

Uses existing `audit_logs` table with OAuth-specific fields:

```sql
action = 'oauth_*' (login, link, unlink, etc.)
resource = 'oauth:provider'
status = 'success' or 'failure'
```

---

## 5. Integration with OAuth Flow

### Updated OAuth Handler

The `OAuthHandler` class now integrates:
- Email verification checks
- Account merge detection
- Audit logging for all operations
- Rate limiting on callbacks

### Example: Complete OAuth Login with All Features

```
1. User initiates OAuth login
   └─ Check rate limit (check_oauth_login_limit)
   └─ Log initiation (log_oauth_initiation)

2. OAuth callback received
   └─ Validate state/code
   └─ Exchange code for token
   └─ Fetch user info
   └─ Check email domain validity
   └─ Detect brute force attempts

3. Find or create user
   └─ Look for existing user by email
   └─ Merge OAuth to existing user if found
   └─ Create new user if needed

4. Email verification (if required)
   └─ Generate verification token
   └─ Return temp account until verified
   └─ Log email verification

5. Generate JWT token
   └─ Log successful login
   └─ Record OAuth attempt success
   └─ Update last login timestamp

6. Return to frontend
   └─ User redirected with JWT
   └─ Session established
   └─ Analytics updated
```

---

## 6. Configuration

### Environment Variables

```env
# Email Verification
OAUTH_EMAIL_VERIFICATION_REQUIRED=True
OAUTH_EMAIL_VERIFICATION_HOURS=24
OAUTH_BLOCK_THROWAWAY_EMAILS=True

# Rate Limiting
OAUTH_RATE_LIMIT_LOGIN=20
OAUTH_RATE_LIMIT_LINK=10
OAUTH_RATE_LIMIT_CALLBACK=50

# Account Merging
OAUTH_AUTO_MERGE_ACCOUNTS=True
OAUTH_MERGE_ON_EMAIL_MATCH=True

# Audit Logging
OAUTH_AUDIT_LOG_ENABLED=True
OAUTH_ANALYTICS_ENABLED=True
```

### Settings Class

```python
class OAuthSecurityConfig:
    EMAIL_VERIFICATION_REQUIRED = True
    EMAIL_VERIFICATION_HOURS = 24
    BLOCK_THROWAWAY_EMAILS = True
    
    RATE_LIMIT_LOGIN = 20
    RATE_LIMIT_LINK = 10
    RATE_LIMIT_CALLBACK = 50
    
    AUTO_MERGE_ACCOUNTS = True
    MERGE_ON_EMAIL_MATCH = True
```

---

## 7. Frontend Updates

### Email Verification UI

For providers requiring verification:

```html
<div id="email-verification-prompt">
    <h3>Verify Your Email</h3>
    <p>We've sent a verification link to {{ email }}</p>
    <button onclick="resendVerification()">Resend Email</button>
    <p>Didn't receive? Check spam folder or contact support</p>
</div>
```

### Account Merge Prompt

When OAuth email matches existing account:

```html
<div id="account-merge-prompt">
    <h3>Link Your Accounts</h3>
    <p>Found existing account with {{ email }}</p>
    <p>Link {{ provider }} account to your existing account?</p>
    <button onclick="confirmMerge()">Yes, Link Accounts</button>
    <button onclick="createNew()">Create New Account</button>
</div>
```

### Abuse Prevention

When rate limit exceeded:

```html
<div id="rate-limit-message">
    <p>Too many attempts. Please try again in 1 hour.</p>
</div>
```

---

## 8. Security Best Practices

### ✅ Implemented

- Email verification for user signup
- Rate limiting on OAuth endpoints
- Brute force detection
- Throwaway email blocking
- Account deduplication
- Comprehensive audit logging
- CSRF protection via state parameter
- Secure token storage (hashed)

### 🔄 Recommended Additional

- Two-factor authentication (2FA)
- Email verification before account access
- IP-based geo-blocking
- Device fingerprinting
- Anomaly detection (login from new location)
- Session invalidation on suspicious activity

---

## 9. Testing

### Unit Tests

```python
# Test email verification
def test_email_verification():
    token = EmailVerificationService.generate_verification_token(
        user_id='test-user',
        email='test@example.com'
    )
    success, user_id = EmailVerificationService.verify_email(token, 'test@example.com')
    assert success and user_id == 'test-user'

# Test account merging
def test_account_merge():
    success, msg = AccountMergeService.merge_oauth_account(
        user_id='existing-user',
        provider_name='google',
        provider_user_id='goog-123'
    )
    assert success

# Test rate limiting
def test_rate_limiting():
    for i in range(20):
        allowed, _ = OAuthRateLimiter.check_oauth_login_limit('192.168.1.1', 'google')
    allowed, _ = OAuthRateLimiter.check_oauth_login_limit('192.168.1.1', 'google')
    assert not allowed  # 21st attempt should fail
```

### Integration Tests

Test complete OAuth flow with all Phase 4 features:
1. Email verification workflow
2. Account merge detection
3. Rate limiting enforcement
4. Audit log generation
5. Abuse pattern detection

---

## 10. Monitoring & Analytics

### Key Metrics

- OAuth login success/failure rate by provider
- Email verification completion rate
- Account merge frequency
- Rate limit violations per hour
- Brute force attempts detected
- Throwaway email rejections

### Dashboard Queries

```python
# OAuth stats for last 7 days
stats = OAuthAnalytics.get_oauth_stats(days=7)

# Provider popularity
popularity = OAuthAnalytics.get_provider_popularity()

# Get suspicious activities
suspicious = session.query(AuditLog).filter_by(
    action='oauth_suspicious_activity'
).all()
```

---

## Phase 4 Summary

| Component | Purpose | Status |
|-----------|---------|--------|
| Email Verification | Verify email ownership | ✅ Complete |
| Account Merging | Dedup accounts by email | ✅ Complete |
| Rate Limiting | Prevent abuse | ✅ Complete |
| Audit Logging | Security monitoring | ✅ Complete |
| Abuse Detection | Identify attacks | ✅ Complete |
| Analytics | Usage tracking | ✅ Complete |

---

## Next Steps

1. Test all Phase 4 components
2. Configure environment variables
3. Set up email delivery (for verification emails)
4. Deploy to staging environment
5. Monitor audit logs and analytics
6. Fine-tune rate limits based on usage
7. Consider additional security features (2FA, geo-blocking)

