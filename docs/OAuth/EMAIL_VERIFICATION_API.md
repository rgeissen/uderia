---
title: Email Verification API
description: API endpoints for email verification in traditional user registration
---

# Email Verification API

This document describes the email verification endpoints for the traditional user registration flow (username/password). These endpoints work alongside the OAuth email verification system.

## Overview

When users register with username and password, they receive a verification email. The email contains a link with a verification token. Users click the link to verify their email address before full account activation.

**Key Features:**
- Automatic verification email on registration
- 24-hour token expiry
- Resend verification email if user didn't receive it
- Email domain validation (blocks throwaway email services)
- Audit logging for all verification events

## Endpoints

### 1. Register User with Email Verification

**POST** `/api/v1/auth/register`

Creates a new user account and sends a verification email.

#### Request

```json
{
  "username": "john_doe",
  "email": "john@example.com",
  "password": "SecurePass123!",
  "display_name": "John Doe",
  "verification_base_url": "http://localhost:3000"
}
```

**Parameters:**
- `username` (required): 3-30 characters, alphanumeric and underscore only
- `email` (required): Valid email address
- `password` (required): Min 8 characters, must include uppercase, lowercase, number, and special character
- `display_name` (optional): 1-100 characters, defaults to username
- `verification_base_url` (optional): Base URL for verification link in email, defaults to `http://localhost:3000`

#### Response (201 Created)

```json
{
  "status": "success",
  "message": "User registered successfully. Please check your email to verify your account.",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "john_doe",
    "user_uuid": "550e8400-e29b-41d4-a716-446655440000",
    "display_name": "John Doe",
    "email_verified": false
  },
  "requires_email_verification": true
}
```

#### Error Responses

**400 Bad Request** - Validation failed
```json
{
  "status": "error",
  "message": "Validation failed",
  "errors": {
    "password": "Password must be at least 8 characters with uppercase, lowercase, number, and special character"
  }
}
```

**409 Conflict** - Username or email already exists
```json
{
  "status": "error",
  "message": "Username already taken"
}
```

**429 Too Many Requests** - Rate limit exceeded
```json
{
  "status": "error",
  "message": "Registration rate limit exceeded",
  "retry_after": 3600
}
```

#### Email Content

The verification email includes:
- Personalized greeting with user's display name
- Prominent "Verify Email Address" button
- Plain text link as fallback
- Note that link expires in 24 hours
- Footer with company information

Sample link format:
```
http://localhost:3000/verify-email?token=abc123xyz...&email=john@example.com
```

---

### 2. Verify Email Address

**POST** `/api/v1/auth/verify-email`

Verifies an email address using the token from the verification email.

#### Request

```json
{
  "token": "eye...JV_aZ6V76e9kFs",
  "email": "john@example.com"
}
```

**Parameters:**
- `token` (required): Verification token from email link
- `email` (required): Email address being verified

#### Response (200 OK)

```json
{
  "status": "success",
  "message": "Email verified successfully",
  "user_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### Error Responses

**400 Bad Request** - Missing fields
```json
{
  "status": "error",
  "message": "Missing token or email"
}
```

**401 Unauthorized** - Invalid or expired token
```json
{
  "status": "error",
  "message": "Invalid or expired verification token"
}
```

**404 Not Found** - User not found
```json
{
  "status": "error",
  "message": "User not found"
}
```

---

### 3. Resend Verification Email

**POST** `/api/v1/auth/resend-verification-email`

Resends the verification email to a user who hasn't verified their email yet.

#### Request

```json
{
  "email": "john@example.com",
  "verification_base_url": "http://localhost:3000"
}
```

**Parameters:**
- `email` (required): User's email address
- `verification_base_url` (optional): Base URL for verification link, defaults to `http://localhost:3000`

#### Response (200 OK)

```json
{
  "status": "success",
  "message": "Verification email sent successfully"
}
```

#### Error Responses

**400 Bad Request** - Missing email or already verified
```json
{
  "status": "error",
  "message": "Email already verified"
}
```

**404 Not Found** - User not found
```json
{
  "status": "error",
  "message": "User not found"
}
```

**429 Too Many Requests** - Rate limit exceeded
```json
{
  "status": "error",
  "message": "Rate limit exceeded",
  "retry_after": 3600
}
```

---

## Frontend Integration Examples

### 1. Registration Form

```javascript
async function registerUser(formData) {
  const response = await fetch('/api/v1/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username: formData.username,
      email: formData.email,
      password: formData.password,
      display_name: formData.displayName,
      verification_base_url: window.location.origin
    })
  });

  const data = await response.json();

  if (response.ok) {
    // Show success message directing user to check email
    showMessage('Registration successful! Check your email to verify your account.');
    redirectToCheckEmail(data.user.email);
  } else {
    // Show validation errors
    showErrors(data.errors || data.message);
  }
}
```

### 2. Email Verification Page

```javascript
async function verifyEmail(token, email) {
  const response = await fetch('/api/v1/auth/verify-email', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, email })
  });

  const data = await response.json();

  if (response.ok) {
    showSuccessMessage('Email verified successfully! You can now log in.');
    redirectToLogin();
  } else {
    showErrorMessage(data.message);
    showResendButton(email);
  }
}
```

### 3. Resend Email

```javascript
async function resendVerificationEmail(email) {
  const response = await fetch('/api/v1/auth/resend-verification-email', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email,
      verification_base_url: window.location.origin
    })
  });

  const data = await response.json();

  if (response.ok) {
    showMessage('Verification email resent. Check your inbox.');
  } else {
    showErrorMessage(data.message);
  }
}
```

---

## Email Configuration

To enable email verification, configure your email provider. See [EMAIL_SETUP.md](./EMAIL_SETUP.md) for detailed setup instructions.

### Required Environment Variables

**SendGrid:**
```env
EMAIL_PROVIDER=sendgrid
SENDGRID_API_KEY=SG.xxxxx
SENDGRID_FROM_EMAIL=verification@yourdomain.com
```

**SMTP:**
```env
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=your-email@gmail.com
```

**AWS SES:**
```env
EMAIL_PROVIDER=aws_ses
AWS_SES_FROM_EMAIL=verification@yourdomain.com
AWS_SES_REGION=us-east-1
```

---

## Security Considerations

### Token Security
- Tokens are hashed in the database using SHA-256
- Raw tokens only exist in the verification email link
- Tokens are never logged or exposed in logs
- 24-hour expiry (configurable in `EmailVerificationService`)

### Rate Limiting
- Registration endpoint limited to 5 attempts per IP per 15 minutes
- Resend endpoint uses same rate limit
- Rate limit errors include `retry_after` field

### Email Validation
- Throwaway email domains are blocked (tempmail, mailinator, etc.)
- Valid email format required
- Email uniqueness enforced at database level

### Audit Logging
- All registration events logged with user ID, action, and timestamp
- All verification events logged with status (success/failure)
- IP address and user agent captured for security analysis

---

## Common Scenarios

### Scenario 1: User Doesn't Receive Email

1. Wait 5 minutes (email propagation delay)
2. Check spam folder
3. Call resend endpoint: `POST /api/v1/auth/resend-verification-email`
4. Check that email provider is configured and has valid credentials

### Scenario 2: Verification Link Expires

1. Call resend endpoint: `POST /api/v1/auth/resend-verification-email`
2. Check new link in email (24-hour expiry from new generation)
3. If still having issues, check email service logs

### Scenario 3: Multiple Verification Attempts

The system allows multiple verification tokens per user. Each call to register or resend generates a new token. Only one needs to be valid to verify the email.

### Scenario 4: User Wants to Verify Later

The user account is created immediately. Email verification status is stored in `user.email_verified` (boolean). Your application can:
- Allow login without verified email (then prompt later)
- Block login until email verified
- Restrict features until email verified

---

## Testing Email Verification

### Local Testing

Use MailHog or similar SMTP mock server:

```bash
# Install MailHog
brew install mailhog

# Run MailHog
mailhog

# Configure in .env
EMAIL_PROVIDER=smtp
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USERNAME=test
SMTP_PASSWORD=test
SMTP_FROM_EMAIL=test@localhost
```

Then access MailHog UI at `http://localhost:8025` to see sent emails.

### Testing with SendGrid

Create a test SendGrid account and use sandbox mode:

```bash
curl -X POST https://api.sendgrid.com/v3/mail/send \
  -H "Authorization: Bearer $SENDGRID_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "personalizations": [{"to": [{"email": "test@example.com"}]}],
    "from": {"email": "noreply@example.com"},
    "subject": "Test Email",
    "content": [{"type": "text/plain", "value": "Test"}]
  }'
```

### API Testing Script

```python
import requests
import json

BASE_URL = "http://localhost:5000"

# 1. Register user
register_data = {
    "username": "testuser",
    "email": "test@example.com",
    "password": "TestPass123!",
    "display_name": "Test User",
    "verification_base_url": "http://localhost:3000"
}

response = requests.post(f"{BASE_URL}/api/v1/auth/register", json=register_data)
print(f"Register: {response.status_code}")
print(json.dumps(response.json(), indent=2))

# 2. Get token from email (manually or from test email provider)
token = "your_token_here"
email = "test@example.com"

# 3. Verify email
verify_data = {"token": token, "email": email}
response = requests.post(f"{BASE_URL}/api/v1/auth/verify-email", json=verify_data)
print(f"Verify: {response.status_code}")
print(json.dumps(response.json(), indent=2))

# 4. Resend verification email
resend_data = {
    "email": "test@example.com",
    "verification_base_url": "http://localhost:3000"
}
response = requests.post(f"{BASE_URL}/api/v1/auth/resend-verification-email", json=resend_data)
print(f"Resend: {response.status_code}")
print(json.dumps(response.json(), indent=2))
```

---

## Troubleshooting

### Email Not Sending

1. **Check email provider configuration**
   - Verify `EMAIL_PROVIDER` env variable is set
   - Check API keys/credentials are valid
   - For SMTP: test connection with `telnet smtp.host 587`

2. **Check logs**
   - Look for "Error sending email via X" messages
   - Check email service logs (SendGrid, AWS SES dashboard, etc.)

3. **Common issues**
   - SendGrid: API key doesn't have mail send permission
   - SMTP: Wrong port (587 for TLS, 465 for SSL)
   - AWS SES: Email address not verified in sandbox mode

### Verification Token Issues

1. **Token expired**
   - Tokens expire after 24 hours
   - User needs to call resend endpoint for new token

2. **Token invalid**
   - Check token matches exactly from email
   - Verify email matches registration email (lowercase)
   - Check token wasn't modified in URL

3. **User not found**
   - Verify user was created successfully (check registration response)
   - User may have been deleted

---

## Integration with OAuth

Email verification works independently for traditional registration:

- **Traditional Registration** (`/register`): Email verification required
- **OAuth Registration**: Optional, depends on provider and configuration
- **Login**: Can proceed without email verification (configure as needed)

Both systems use the same `EmailVerificationToken` model and can be used together or separately.
