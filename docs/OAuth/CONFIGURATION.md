# OAuth Configuration Checklist

Complete verification and testing guide for your OAuth setup.

---

## 🚀 Quick Start (5-15 minutes)

Follow these steps to configure OAuth:

### Step 1: Get Credentials

Choose which providers you want:
- [ ] **Google** (5-10 min, most popular)
- [ ] **GitHub** (3-5 min, easiest)
- [ ] **Microsoft** (10-15 min, enterprise)
- [ ] **Discord** (2-3 min, communities)
- [ ] **Okta** (10-15 min, enterprise SSO)

See [SETUP_GUIDE.md](./SETUP_GUIDE.md) for step-by-step instructions for each.

### Step 2: Fill .env File

```bash
# Open .env (in project root)
nano .env

# For development, ensure:
OAUTH_HTTPS_ONLY=False
OAUTH_INSECURE_TRANSPORT=True
OAUTH_CALLBACK_URL=http://localhost:8000/api/v1/auth/oauth/{provider}/callback

# Add provider credentials:
OAUTH_GOOGLE_CLIENT_ID=your_id
OAUTH_GOOGLE_CLIENT_SECRET=your_secret
# ... repeat for each provider
```

### Step 3: Verify Configuration

```bash
./verify_oauth_config.sh
```

All providers should show: `✅ Configured`

### Step 4: Test

```bash
python -m trusted_data_agent
# Open http://localhost:8000/login
# Click OAuth provider button
# Complete login flow
```

---

## 🔧 Configuration Details

### Core Settings

| Setting | Development | Production | Purpose |
|---------|-----------|-----------|---------|
| `OAUTH_HTTPS_ONLY` | `False` | `True` | Require HTTPS |
| `OAUTH_INSECURE_TRANSPORT` | `True` | `False` | Allow HTTP |
| `OAUTH_CALLBACK_URL` | `http://localhost:8000/...` | `https://yourdomain.com/...` | Callback URL |

### Provider Credentials Template

```env
# Google OAuth
OAUTH_GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
OAUTH_GOOGLE_CLIENT_SECRET=xxx

# GitHub OAuth
OAUTH_GITHUB_CLIENT_ID=xxx
OAUTH_GITHUB_CLIENT_SECRET=xxx

# Microsoft OAuth
OAUTH_MICROSOFT_CLIENT_ID=xxx
OAUTH_MICROSOFT_CLIENT_SECRET=xxx

# Discord OAuth
OAUTH_DISCORD_CLIENT_ID=xxx
OAUTH_DISCORD_CLIENT_SECRET=xxx

# Okta OAuth
OKTA_DOMAIN=https://your-tenant.okta.com
OAUTH_OKTA_CLIENT_ID=xxx
OAUTH_OKTA_CLIENT_SECRET=xxx
```

---

## ✅ Configuration Checklist

### Before Configuration
- [ ] Read [GETTING_STARTED.md](./GETTING_STARTED.md)
- [ ] Choose 1-5 providers
- [ ] Have provider credentials ready

### Provider Setup
For each provider:
- [ ] Go to provider's developer dashboard
- [ ] Create new OAuth application
- [ ] Register callback URI: `http://localhost:8000/api/v1/auth/oauth/{provider}/callback`
- [ ] Copy Client ID
- [ ] Copy Client Secret

### .env Configuration
- [ ] `.env` file exists (or copy from `.env.oauth.template`)
- [ ] `OAUTH_HTTPS_ONLY=False` (development)
- [ ] `OAUTH_INSECURE_TRANSPORT=True` (development)
- [ ] `OAUTH_CALLBACK_URL` matches provider registrations
- [ ] All provider credentials filled in
- [ ] No empty credential fields
- [ ] File saved

### Verification
- [ ] Run: `./verify_oauth_config.sh`
- [ ] All providers show ✅ Configured
- [ ] No ❌ NOT SET errors
- [ ] No warnings about missing variables

### Testing in App
- [ ] Start: `python -m trusted_data_agent`
- [ ] No OAuth errors in console
- [ ] App starts successfully

### Testing Providers Endpoint
```bash
curl http://localhost:8000/api/v1/auth/oauth/providers
```
- [ ] Returns HTTP 200
- [ ] Lists all configured providers
- [ ] Each provider shows `"configured": true`

### Testing Login Flow
1. Open: `http://localhost:8000/login`
   - [ ] OAuth buttons display
   - [ ] Provider icons visible
   - [ ] Buttons clickable

2. Click provider button
   - [ ] Redirected to provider's login page
   - [ ] Provider name shown in page title

3. Login at provider
   - [ ] Can enter credentials
   - [ ] Can complete 2FA if needed

4. Approve/Consent
   - [ ] See consent screen with app name and logo
   - [ ] Can click "Allow" or equivalent

5. Callback to your app
   - [ ] Redirected back to your app
   - [ ] No errors in URL
   - [ ] User is logged in
   - [ ] See user profile/name (if implemented)

---

## 🔐 Security Checklist

For Development:
- [ ] `.env` file in `.gitignore` (not committed)
- [ ] `OAUTH_HTTPS_ONLY=False`
- [ ] `OAUTH_INSECURE_TRANSPORT=True`
- [ ] Using localhost/127.0.0.1

For Production:
- [ ] `.env` in `.gitignore` (never commit secrets)
- [ ] `OAUTH_HTTPS_ONLY=True`
- [ ] `OAUTH_INSECURE_TRANSPORT=False`
- [ ] Using real HTTPS domain
- [ ] Secrets in environment variables (not .env)
- [ ] Different credentials than development
- [ ] Rate limiting enabled
- [ ] Email verification enabled
- [ ] Audit logging enabled

---

## ❌ Common Issues & Solutions

### "Provider not configured"

**Cause**: Credentials not in .env or app not restarted

**Solution**:
```bash
# 1. Verify .env exists
ls -la .env

# 2. Check it has values
grep OAUTH_GOOGLE .env

# 3. Restart the app
# Kill current process and restart:
python -m trusted_data_agent
```

### "Invalid redirect_uri"

**Cause**: Callback URL doesn't match provider settings

**Solution**:
1. Go to provider's developer dashboard
2. Check registered redirect URIs
3. Must match EXACTLY: `http://localhost:8000/api/v1/auth/oauth/google/callback`
   - Not: `http://localhost:8000/oauth/...` (missing `/api/v1/auth`)
   - Not: `http://localhost:8000/api/v1/auth/oauth/google` (missing `/callback`)
4. Update in provider if wrong
5. Clear browser cookies
6. Try again

### "Client ID/Secret invalid"

**Cause**: Wrong credentials or secrets expired

**Solution**:
1. Verify you're copying Client ID (not Secret) to Client ID field
2. Go to provider's dashboard
3. Check for expiration dates
4. Regenerate secret if expired
5. Copy new secret to .env
6. Restart app

### "CORS error" or "Domain mismatch"

**Cause**: Domain in .env doesn't match provider settings

**Solution**:
1. Check `OAUTH_CALLBACK_URL` in .env
2. Check registered URIs in provider dashboard
3. They must match EXACTLY
4. For localhost: ensure `http://` not `https://`
5. For production: ensure `https://` and correct domain
6. Clear browser cookies
7. Try again

### "Button doesn't show"

**Cause**: Provider not configured or app error

**Solution**:
```bash
# Check if provider is configured
./verify_oauth_config.sh

# Check app console for errors
# In browser DevTools:
# - Open Console tab
# - Look for JavaScript errors
# - Check Network tab for failed requests
```

### "State parameter mismatch"

**Cause**: Session lost or CSRF attack attempt

**Solution**:
1. Clear browser cookies
2. Close and reopen browser
3. Try login again
4. If persists, restart app

### ".env file not loading"

**Cause**: App not finding or reading .env

**Solution**:
```bash
# Verify file exists and is readable
ls -la .env
cat .env | head -20

# Verify in app root directory
pwd
# Should be: /Users/livin2rave/my_private_code/uderia

# Restart app
# Stop with Ctrl+C
# Run again: python -m trusted_data_agent
```

---

## 🧪 Step 5: Test the Implementation

### Test 1: Providers List

```bash
curl http://localhost:8000/api/v1/auth/oauth/providers

# Expected response:
# {
#   "providers": [
#     {
#       "id": "google",
#       "name": "Google",
#       "configured": true,
#       "icon_url": "..."
#     },
#     ...
#   ]
# }
```

**Success**: All configured providers show `"configured": true`

### Test 2: Redirect to Provider

Open in browser:
```
http://localhost:8000/api/v1/auth/oauth/google
```

**Success**: Redirected to Google login page

### Test 3: Complete Login Flow

1. Go to: `http://localhost:8000/login`
2. See OAuth buttons
3. Click provider button
4. Login at provider
5. Click "Allow"
6. Return to your app
7. Should be logged in

**Success**: User profile visible or logged-in state confirmed

---

## 📋 Step 6: Phase 4 Features (Optional)

### Email Verification

See [SECURITY.md#email-verification](./SECURITY.md#email-verification)

```bash
# Test email verification
curl -X POST http://localhost:8000/api/v1/auth/email/send-verification \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com"}'
```

### Rate Limiting

See [SECURITY.md#rate-limiting](./SECURITY.md#rate-limiting)

Should block after:
- 20 login attempts per hour per IP
- 10 link attempts per hour per user
- 50 callback attempts per hour per IP

### Audit Logging

See [SECURITY.md#audit-logging](./SECURITY.md#audit-logging)

Check logs:
- All OAuth events logged
- Suspicious activities detected
- Analytics available

---

## 📊 Configuration Summary

| Component | Status | Notes |
|-----------|--------|-------|
| Backend | ✅ Ready | All code implemented |
| Frontend | ✅ Ready | UI buttons created |
| Database | ✅ Ready | Models created |
| Configuration | 🔄 In Progress | You are here |
| Testing | ⏳ Pending | Test after config |
| Email | ⏳ Pending | Configure after |
| Production | ⏳ Pending | Deploy after testing |

---

## 📞 Troubleshooting Resources

| Issue | Resource |
|-------|----------|
| Setup help | [SETUP_GUIDE.md](./SETUP_GUIDE.md) |
| Provider-specific | [SETUP_GUIDE.md#troubleshooting](./SETUP_GUIDE.md#troubleshooting) |
| How OAuth works | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| Code integration | [INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md) |
| Security features | [SECURITY.md](./SECURITY.md) |

---

**Next Steps:**
1. ✅ Configure .env with credentials
2. ✅ Run verification script
3. ✅ Test in browser
4. 📋 [SECURITY.md](./SECURITY.md) - Set up email and rate limiting
5. 📋 Deploy to production

**Go back to:** [README.md](./README.md) | [GETTING_STARTED.md](./GETTING_STARTED.md)
