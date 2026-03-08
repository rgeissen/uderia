# Google OAuth Testing Guide

Complete testing procedures for Google OAuth with email verification integration.

## 📋 Prerequisites

Before testing, ensure you have:

1. ✅ Google OAuth credentials configured in `.env`
   ```bash
   OAUTH_GOOGLE_CLIENT_ID=your_client_id_here
   OAUTH_GOOGLE_CLIENT_SECRET=your_client_secret_here
   ```

2. ✅ Application running on `http://localhost:5050`
   ```bash
   conda run -n tda python -m trusted_data_agent.main --nogitcall
   ```

3. ✅ Email service configured (SMTP, SendGrid, or AWS SES)
   - Check `.env` for `EMAIL_PROVIDER` settings

4. ✅ Test Google account(s) ready
   - Use a real Google account (or create one for testing)
   - At least 2 accounts recommended for multi-user testing

---

## 🧪 Test Scenarios

### Scenario 1: Fresh Google OAuth User Registration & Login

**Objective:** Verify that a new user can register and login via Google OAuth

**Steps:**
1. Navigate to `http://localhost:5050/login`
2. Click "Sign in with Google" button
3. Complete Google authentication flow
4. Verify redirect back to application
5. Check that user is logged in and can access dashboard

**Expected Results:**
- ✅ User account created automatically
- ✅ `email_verified=true` (Google verified the email)
- ✅ User can immediately access dashboard (no email verification required)
- ✅ User data matches Google profile (email, name, picture)
- ✅ JWT token issued successfully

**Database Verification:**
```bash
sqlite3 tda_auth.db "SELECT username, email, email_verified FROM users WHERE email LIKE '%gmail.com%' OR email LIKE '%google%' LIMIT 1;"
```

Expected output: `username | email@gmail.com | 1`

---

### Scenario 2: Repeat Login with Same Google Account

**Objective:** Verify that existing OAuth users can login again

**Steps:**
1. Logout from application (or open in incognito window)
2. Navigate to `http://localhost:5050/login`
3. Click "Sign in with Google"
4. Complete Google authentication
5. Verify redirect and access to dashboard

**Expected Results:**
- ✅ No new user created (same account linked)
- ✅ `last_login_at` timestamp updated
- ✅ OAuth account marked as last used
- ✅ Instant access to dashboard

**Database Verification:**
```bash
sqlite3 tda_auth.db "SELECT provider, last_used_at FROM oauth_accounts WHERE provider='google' LIMIT 1;"
```

---

### Scenario 3: Email Verification Status Sync

**Objective:** Verify that email verification status is correctly synced from Google

**Steps:**
1. Create new Google OAuth account
2. Check database for `email_verified` status
3. Login again with same account
4. Verify status remains synced

**Expected Results:**
- ✅ Initial signup: `email_verified=1` (Google verified)
- ✅ After re-login: `email_verified=1` (stays synced)
- ✅ No email verification prompts shown

**Code Path Being Tested:**
- `src/trusted_data_agent/auth/oauth_handlers.py:383` - Initial user creation with email_verified
- `src/trusted_data_agent/auth/oauth_handlers.py:297-301` - Email verification sync on re-login

---

### Scenario 4: Multiple Google Accounts

**Objective:** Verify that multiple Google accounts can register and login independently

**Steps:**
1. Use first Google account to register (complete flow)
2. Logout
3. Use different Google account to register
4. Login with each account alternately
5. Verify each user has their own session/data

**Expected Results:**
- ✅ Two separate user accounts created
- ✅ Each account linked to correct OAuth account
- ✅ Proper user isolation (user A can't see user B's data)
- ✅ Both can login successfully

**Database Verification:**
```bash
sqlite3 tda_auth.db "SELECT user_id, provider_email FROM oauth_accounts WHERE provider='google';"
```

---

### Scenario 5: Email Verification Page - OAuth Users

**Objective:** Verify that OAuth users don't see email verification screens

**Steps:**
1. Create new Google OAuth user
2. Check if email verification page appears
3. Check if "Verify email" messages appear on login

**Expected Results:**
- ✅ No email verification page shown (Google verified)
- ✅ No "Email not verified" error messages
- ✅ Direct access to dashboard

---

### Scenario 6: Account Information Sync

**Objective:** Verify that user profile data is correctly synced from Google

**Steps:**
1. Register with Google OAuth
2. Check database for synchronized data:
   - Email address
   - Display name
   - Profile picture URL

**Database Verification:**
```bash
sqlite3 tda_auth.db "SELECT username, email, display_name FROM users ORDER BY created_at DESC LIMIT 1;"
sqlite3 tda_auth.db "SELECT provider_email, provider_name, provider_picture_url FROM oauth_accounts WHERE provider='google' LIMIT 1;"
```

---

## 🔍 Logging Verification

Monitor application logs during testing to verify correct behavior:

### Key Log Messages to Look For

**Successful OAuth Flow:**
```
INFO - User logged in: [username] (via google)
INFO - Successful OAuth login for user [user_id] via google
INFO - Successfully fetched user info from google
```

**Email Verification:**
```
INFO - Generated jwt_token for user [user_id] via google
DEBUG - Email verification status: email_verified=true (from Google)
```

**Account Linking:**
```
INFO - Created OAuth account link for user [user_id]
INFO - Updated existing OAuth account for user [user_id]
```

### Watch for Error Messages:
- ❌ `Error exchanging code for token`
- ❌ `Failed to fetch user info from google`
- ❌ `OAuth authorization failed`
- ❌ `Provider not configured`

---

## 📊 Test Case Matrix

| Scenario | User Type | Email Verified | Can Login | Expected Behavior |
|----------|-----------|---|---|---|
| First Google signup | New | ✅ Yes | ✅ Yes | Create user, instant access |
| Repeat Google login | Existing | ✅ Yes | ✅ Yes | Update last_login, instant access |
| Multi-account test | Multiple | ✅ Yes each | ✅ Yes each | Separate accounts, proper isolation |
| Email sync | Existing | ✅ Yes | ✅ Yes | Status remains synced |
| Profile update | Existing | ✅ Yes | ✅ Yes | Name/picture may sync |

---

## 🐛 Debugging & Troubleshooting

### Issue: "Provider not configured"

**Check:**
1. `.env` file has `OAUTH_GOOGLE_CLIENT_ID` set
2. `.env` file has `OAUTH_GOOGLE_CLIENT_SECRET` set
3. App restarted after updating `.env`

```bash
# Verify credentials loaded
grep OAUTH_GOOGLE /Users/livin2rave/my_private_code/uderia/.env
```

### Issue: "Failed to fetch user info"

**Check:**
1. Network connectivity to Google API
2. Client ID and secret are correct
3. Google project has OAuth 2.0 scope enabled
4. Redirect URI matches Google console settings

### Issue: User email_verified=0 (false)

**Check:**
1. Google returned `email_verified=false` (shouldn't happen)
2. Code path in `oauth_handlers.py` line 383 was updated
3. App was restarted after code changes

```bash
# Check the code:
grep -n "email_verified" src/trusted_data_agent/auth/oauth_handlers.py
```

### Issue: Can't see logs

**Solutions:**
1. Check that application is running: `lsof -i :5050`
2. Increase log level in `src/trusted_data_agent/main.py`
3. Search logs for "google": `grep -i google /path/to/logs`

---

## 📈 Performance Testing

### Test High-Volume OAuth Logins

```bash
# Script to simulate multiple logins (requires curl and jq)
for i in {1..10}; do
  echo "Iteration $i..."
  curl -s "http://localhost:5050/api/v1/auth/oauth/google?code=test" 2>&1 | head -5
  sleep 1
done
```

---

## 🔒 Security Testing

### Test 1: State Parameter Validation
- Verify CSRF protection is working
- Attempt OAuth with mismatched state
- Should receive error

### Test 2: Token Expiry
- Google tokens should expire properly
- Refresh token flow should work
- Users logged out after token expires

### Test 3: Email Verification Bypass
- Verify users can't bypass email verification check
- Email field must be verified before login
- No hardcoded verification bypasses

---

## ✅ Checklist Before Going to Production

- [ ] At least 3 successful Google OAuth registrations
- [ ] At least 3 successful repeat logins with same accounts
- [ ] Email verification status correctly set to true for Google users
- [ ] User profile data (email, name, picture) synced correctly
- [ ] OAuth accounts properly linked in database
- [ ] Logs show no errors or warnings during OAuth flow
- [ ] Multiple Google accounts work independently
- [ ] No email verification required for Google users
- [ ] CSRF state parameter validated
- [ ] OAuth tokens expire properly
- [ ] Redirect URIs match Google console settings

---

## 📝 Test Report Template

```
Date: ___________
Tester: ___________
Google Account Email: ___________

✅ Fresh Registration
  - Redirect successful: YES / NO
  - User created: YES / NO
  - email_verified=true: YES / NO
  - Can access dashboard: YES / NO
  - Notes: ___________

✅ Repeat Login
  - Authentication successful: YES / NO
  - No duplicate user created: YES / NO
  - last_login_at updated: YES / NO
  - No email verification prompts: YES / NO
  - Notes: ___________

✅ Profile Sync
  - Email synced correctly: YES / NO
  - Display name synced: YES / NO
  - Picture URL synced: YES / NO
  - Notes: ___________

✅ Logs
  - No errors in application logs: YES / NO
  - Correct user ID in logs: YES / NO
  - Notes: ___________

Overall Status: PASS / FAIL
Issues Found: ___________
```

---

## 🔗 Related Documentation

- [OAUTH.md](./OAUTH.md) - Overview
- [SETUP_GUIDE.md](./SETUP_GUIDE.md) - Google credentials setup
- [SECURITY.md](./SECURITY.md) - Security features
- [EMAIL_VERIFICATION_OAUTH_ALIGNMENT.md](../EMAIL_VERIFICATION_OAUTH_ALIGNMENT.md) - Email verification with OAuth
- [CONFIGURATION.md](./CONFIGURATION.md) - Configuration verification

---

**Last Updated:** 2026-01-02  
**Status:** ✅ Complete
