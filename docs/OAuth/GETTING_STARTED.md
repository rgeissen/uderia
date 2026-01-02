# OAuth Getting Started Guide

**Start here!** This guide walks you through configuring OAuth in 15-30 minutes.

---

## 📍 Where You Are

✅ **Completed:**
- All OAuth backend code implemented (4 phases)
- OAuth frontend UI created
- Database models ready
- Configuration templates created
- Verification tools created

🔄 **Now:** Configure your OAuth providers

⏳ **Next:** Test the complete flow

---

## ⚡ 5-Minute Quick Start

### Step 1: Choose a Provider
- **Google** (fastest): 5-10 minutes
- **GitHub** (easiest): 3-5 minutes

### Step 2: Get Credentials
Follow [SETUP_GUIDE.md](./SETUP_GUIDE.md) for your chosen provider

### Step 3: Add to .env
```bash
# Edit .env file in project root
nano .env

# Add your credentials:
OAUTH_GOOGLE_CLIENT_ID=your_id_here
OAUTH_GOOGLE_CLIENT_SECRET=your_secret_here
```

### Step 4: Verify
```bash
./verify_oauth_config.sh
```

### Step 5: Test
```bash
python -m trusted_data_agent
# Then open http://localhost:8000/login
```

**Total Time: 15-30 minutes**

---

## 📚 Complete Setup Walkthrough

### Option A: MVP Setup (Recommended for First Time)

**Time: 15 minutes**

1. **Get Google OAuth credentials** (5-10 min)
   - Open https://console.cloud.google.com
   - Follow section "Google OAuth Setup" in [SETUP_GUIDE.md](./SETUP_GUIDE.md)
   - Copy Client ID and Secret

2. **Fill in .env** (2 min)
   ```bash
   nano .env
   # Add:
   # OAUTH_GOOGLE_CLIENT_ID=xxx
   # OAUTH_GOOGLE_CLIENT_SECRET=xxx
   ```

3. **Verify** (1 min)
   ```bash
   ./verify_oauth_config.sh
   # Should show ✅ for Google
   ```

4. **Test** (2 min)
   ```bash
   python -m trusted_data_agent
   open http://localhost:8000/login
   # Click "Google" button
   ```

✅ **Result**: OAuth works! You can add more providers later.

---

### Option B: Full Setup

**Time: 45 minutes**

1. Get credentials for multiple providers (30-35 min)
   - Google (5-10 min) - [SETUP_GUIDE.md#google-oauth-setup](./SETUP_GUIDE.md#google-oauth-setup)
   - GitHub (3-5 min) - [SETUP_GUIDE.md#github-oauth-setup](./SETUP_GUIDE.md#github-oauth-setup)
   - Microsoft (10-15 min) - [SETUP_GUIDE.md#microsoft-oauth-setup](./SETUP_GUIDE.md#microsoft-oauth-setup)
   - Discord (2-3 min) - [SETUP_GUIDE.md#discord-oauth-setup](./SETUP_GUIDE.md#discord-oauth-setup)
   - Okta (10-15 min) - [SETUP_GUIDE.md#okta-oauth-setup](./SETUP_GUIDE.md#okta-oauth-setup)

2. Fill .env with all credentials (3 min)

3. Verify configuration (1 min)
   ```bash
   ./verify_oauth_config.sh
   # All providers should show ✅ Configured
   ```

4. Test in browser (2 min)

✅ **Result**: All OAuth providers working!

---

## 🚀 Recommended Approach

For your first setup, we recommend **Option A (MVP)**:

1. Pick **Google** or **GitHub** (both ~5 min)
2. Get credentials (follow [SETUP_GUIDE.md](./SETUP_GUIDE.md))
3. Add to `.env`
4. Run verification script
5. Test in browser

This proves OAuth works. You can add more providers anytime by:
1. Getting credentials for next provider
2. Adding to `.env`
3. Restarting app

---

## 📋 What You Need

### For Development (Local Machine)
```env
OAUTH_HTTPS_ONLY=False
OAUTH_INSECURE_TRANSPORT=True
OAUTH_CALLBACK_URL=http://localhost:8000/api/v1/auth/oauth/{provider}/callback
```

### For Each Provider (Choose 1+)
```env
# Google
OAUTH_GOOGLE_CLIENT_ID=xxx
OAUTH_GOOGLE_CLIENT_SECRET=xxx

# GitHub
OAUTH_GITHUB_CLIENT_ID=xxx
OAUTH_GITHUB_CLIENT_SECRET=xxx

# Microsoft
OAUTH_MICROSOFT_CLIENT_ID=xxx
OAUTH_MICROSOFT_CLIENT_SECRET=xxx

# Discord
OAUTH_DISCORD_CLIENT_ID=xxx
OAUTH_DISCORD_CLIENT_SECRET=xxx

# Okta
OKTA_DOMAIN=https://your-domain.okta.com
OAUTH_OKTA_CLIENT_ID=xxx
OAUTH_OKTA_CLIENT_SECRET=xxx
```

---

## 🔑 OAuth Providers Comparison

| Provider | Setup Time | Best For | Difficulty |
|----------|-----------|----------|-----------|
| **Google** | 5-10 min | Mass market | Easy |
| **GitHub** | 3-5 min | Developers | Easy |
| **Microsoft** | 10-15 min | Enterprise | Medium |
| **Discord** | 2-3 min | Communities | Easy |
| **Okta** | 10-15 min | Enterprise SSO | Medium |

**Recommendation**: Start with **Google** or **GitHub**

---

## 🔄 How OAuth Works

### Simple Overview

```
1. User clicks "Sign in with Google"
   ↓
2. Your app redirects to Google login
   ↓
3. User logs in at Google
   ↓
4. Google redirects back to your app with code
   ↓
5. Your app exchanges code for user info
   ↓
6. Your app creates session for user
   ↓
7. User is logged in ✅
```

### Technical Flow

```
Browser                 Your App              Provider (Google)
  │                        │                         │
  ├─ Click button ────────→ │                         │
  │                        │                         │
  │◄───── Redirect ────────│────────────────────────→│
  │       to provider   (with client_id, state)      │
  │                        │                         │
  ├─ User logs in     ┌────────────────────────────┐ │
  │  and approves     │  Google authentication     │ │
  │                  └────────────────────────────┘ │
  │                        │                         │
  │◄───── Redirect ────────│◄───────────────────────┤
  │       with code,  (code + state)                 │
  │       state                                       │
  │                   ┌─────────────────────────┐   │
  │                   │ Verify state matches    │   │
  │                   │ Exchange code → token   │   │
  │                   └─────────────────────────┘   │
  │                        │                         │
  │                        ├─ Server-to-server ────→│
  │                        │ (hidden from user)     │
  │                        │                        │
  │                        │◄─ Access token ─────── │
  │                        │                         │
  │                   ┌─────────────────────────┐   │
  │                   │ Use token to get        │   │
  │                   │ user profile            │   │
  │                   └─────────────────────────┘   │
  │                        │                         │
  │                        ├─ Get user info ──────→│
  │                        │                        │
  │                        │◄─ User data ───────── │
  │                        │                         │
  │                   ┌─────────────────────────┐   │
  │                   │ Create user in database │   │
  │                   │ Generate JWT token      │   │
  │                   └─────────────────────────┘   │
  │                        │                         │
  │◄───── JWT Token ──────│                         │
  │                        │                         │
  ├─ Store JWT            │                         │
  │  in localStorage       │                         │
  │                        │                         │
  └─ You're logged in! ✅  │                         │
```

For more details, see [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## 📖 Reading Order

Read these in order:

1. **This file** (you are here) - Overview and quick start
2. **[SETUP_GUIDE.md](./SETUP_GUIDE.md)** - How to get credentials for your chosen provider(s)
3. **[CONFIGURATION.md](./CONFIGURATION.md)** - How to configure and verify .env
4. **[ARCHITECTURE.md](./ARCHITECTURE.md)** - How OAuth flow works (optional but helpful)
5. **[INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md)** - How to use OAuth in your code
6. **[SECURITY.md](./SECURITY.md)** - Security features and email verification

---

## ✅ Configuration Checklist

### Before You Start
- [ ] Read this guide
- [ ] Choose 1-2 providers to start with
- [ ] Have your browser ready

### Getting Credentials
- [ ] Pick provider(s) from [SETUP_GUIDE.md](./SETUP_GUIDE.md)
- [ ] Go to provider's developer dashboard
- [ ] Create OAuth application
- [ ] Register callback URL: `http://localhost:8000/api/v1/auth/oauth/{provider}/callback`
- [ ] Copy Client ID
- [ ] Copy Client Secret

### Configuration
- [ ] Open `.env` file (in project root)
- [ ] Add `OAUTH_GOOGLE_CLIENT_ID=xxx` (if using Google)
- [ ] Add `OAUTH_GOOGLE_CLIENT_SECRET=xxx` (if using Google)
- [ ] Repeat for each provider
- [ ] Verify `OAUTH_HTTPS_ONLY=False` (for development)
- [ ] Verify `OAUTH_INSECURE_TRANSPORT=True` (for development)

### Verification
- [ ] Run: `./verify_oauth_config.sh`
- [ ] All providers show ✅ Configured
- [ ] No ❌ NOT SET errors

### Testing
- [ ] Start app: `python -m trusted_data_agent`
- [ ] Open browser: `http://localhost:8000/login`
- [ ] See OAuth provider buttons
- [ ] Click a provider button
- [ ] Redirected to provider's login
- [ ] Complete login
- [ ] Returned to your app logged in ✅

---

## 🧪 Quick Test

After configuring, test with:

```bash
# 1. Start your app
python -m trusted_data_agent

# 2. In another terminal, check providers
curl http://localhost:8000/api/v1/auth/oauth/providers

# 3. Should return JSON with available providers
# 4. Open browser to http://localhost:8000/login
# 5. Click a provider button
# 6. Login with that provider's account
# 7. Should be logged into your app
```

---

## 🚫 Common Mistakes

### ❌ Wrong Callback URL
- **Wrong**: `http://localhost:8000/login`
- **Right**: `http://localhost:8000/api/v1/auth/oauth/google/callback`
- **Action**: Register exact URL in provider's dashboard

### ❌ HTTPS for Development
- **Wrong**: `OAUTH_HTTPS_ONLY=True` for localhost
- **Right**: `OAUTH_HTTPS_ONLY=False` for development
- **Action**: Change to `True` before production

### ❌ Copying Wrong Field
- **Wrong**: Copying Client ID to Client Secret field
- **Right**: Copy Client ID to `OAUTH_GOOGLE_CLIENT_ID`
- **Right**: Copy Client Secret to `OAUTH_GOOGLE_CLIENT_SECRET`
- **Action**: Double-check field names in .env

### ❌ Using Wrong Domain
- **Wrong**: `https://yourdomain.com` for localhost testing
- **Right**: `http://localhost:8000` for development
- **Action**: Register different URIs for dev/prod in provider

---

## 📞 Need Help?

**Setup Issues?** → [SETUP_GUIDE.md#troubleshooting](./SETUP_GUIDE.md#troubleshooting)

**Configuration Issues?** → [CONFIGURATION.md#common-issues](./CONFIGURATION.md#common-issues--solutions)

**How does OAuth work?** → [ARCHITECTURE.md](./ARCHITECTURE.md)

**Code integration?** → [INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md)

**API reference?** → [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)

---

## 🎉 Success Indicators

You know it's working when:

✅ `./verify_oauth_config.sh` shows all providers as ✅ Configured

✅ `curl http://localhost:8000/api/v1/auth/oauth/providers` returns provider list

✅ Login page at `http://localhost:8000/login` shows OAuth buttons

✅ Clicking a provider button redirects to that provider's login

✅ After login and approval, you return to your app logged in

---

## 🎯 Next Steps

### Immediate (Now)
1. ✅ Read [SETUP_GUIDE.md](./SETUP_GUIDE.md)
2. ✅ Get credentials for 1 provider
3. ✅ Fill .env
4. ✅ Run verification script
5. ✅ Test in browser

### Short Term (1-2 hours)
- Add more providers (optional)
- Set up email verification ([SECURITY.md](./SECURITY.md#email-verification))
- Enable rate limiting ([SECURITY.md](./SECURITY.md#rate-limiting))

### Medium Term (1-2 days)
- Test complete OAuth flow
- Test all security features
- Test in different browsers

### Long Term (Before production)
- Update .env for production
- Configure email service
- Deploy to production

---

**Next Step:** [SETUP_GUIDE.md](./SETUP_GUIDE.md)

Choose your provider and follow along!
