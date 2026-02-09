# n8n Workflow Deployment Guide

**For:** https://n8n.uderia.com/
**Date:** 2026-02-09

---

## Quick Import Instructions (5 Minutes)

### Step 1: Create Uderia API Token Credential

1. **Login to n8n:**
   - Go to https://n8n.uderia.com/
   - Login with your credentials

2. **Create Credential:**
   - Click **Settings** (gear icon) → **Credentials**
   - Click **"+ New Credential"**
   - Search for **"Header Auth"**
   - Configure:
     ```
     Name: Uderia API Token
     Header Name: Authorization
     Header Value: Bearer tda_gHjwAvSmq9QIJ-8F35mUxysUv6-l-k6Q
     ```
   - Click **"Create"**

### Step 2: Import Simple Query Workflow

1. **Create New Workflow:**
   - Click **"+ New workflow"** (top left)

2. **Import JSON:**
   - Click **"⋮"** menu (top right)
   - Select **"Import from File"**
   - Choose: `docs/n8n/workflows/simple-query.json`
   - Workflow will load with 14 nodes

3. **Configure Nodes:**
   - Click on **"Create Session"** node
   - Under **"Authentication"** section:
     - Credential Type: **Existing credential**
     - Select: **"Uderia API Token"**
   - Repeat for:
     - **"Submit Query"** node
     - **"Poll Task Status"** node

4. **Update Base URL (if needed):**
   - If Uderia is not on localhost:5050, update each HTTP Request node:
     - **Create Session:** Change URL to `http://YOUR_UDERIA_HOST/api/v1/sessions`
     - **Submit Query:** Change URL to `http://YOUR_UDERIA_HOST/api/v1/sessions/...`
     - **Poll Task Status:** Change URL to `http://YOUR_UDERIA_HOST/api/v1/tasks/...`

5. **Save Workflow:**
   - Click **"Save"** button (top right)
   - Name: "Uderia Simple Query"

### Step 3: Test Execution

1. **Execute:**
   - Click **"Execute Workflow"** button (top right)

2. **Watch Execution:**
   - Nodes will turn green as they execute
   - Polling loop will run 2-3 times
   - Total time: ~5-10 seconds

3. **Check Results:**
   - Click on **"Extract Answer"** node
   - View output panel (bottom)
   - Should see:
     ```json
     {
       "final_answer": "...",
       "profile_tag": "VAT",
       "input_tokens": 1469,
       "output_tokens": 633,
       "total_tokens": 2102
     }
     ```

**✅ If successful, proceed to import other workflows!**

---

## Import Scheduled Report Workflow

### Prerequisites
- SMTP account configured in n8n (for email sending)

### Steps

1. **Import Workflow:**
   - New workflow → Import from File
   - Select: `docs/n8n/workflows/scheduled-report.json`

2. **Configure Credentials:**
   - **Uderia API Token:** Same as Step 1 above (already created)
   - **SMTP Credential:**
     - Settings → Credentials → New
     - Type: **"SMTP"**
     - Configure your email server settings
     - Name: "SMTP Account"

3. **Configure Nodes:**
   - Assign "Uderia API Token" to:
     - Create Session
     - Submit Report Query
     - Poll Task Status
   - Assign "SMTP Account" to:
     - Send Email Report
     - Send Error Notification

4. **Update Email Addresses:**
   - **"Send Email Report"** node:
     - From: `reports@uderia.com` → Your email
     - To: `team@example.com` → Recipient email
   - **"Send Error Notification"** node:
     - From: `alerts@uderia.com` → Your email
     - To: `admin@example.com` → Admin email

5. **Adjust Schedule (Optional):**
   - **"Daily at 8 AM"** node (cron trigger)
   - Default: `0 8 * * *` (8:00 AM daily)
   - For testing: `*/5 * * * *` (every 5 minutes)

6. **Save & Activate:**
   - Save workflow
   - Toggle **"Active"** switch (top right)

### Testing

**Manual Test:**
1. Click **"Execute Workflow"** to test manually first
2. Check your email for report delivery
3. If successful, activate for scheduled execution

**Monitor:**
- Check **"Executions"** tab for daily runs
- Verify emails arrive at expected time

---

## Import Slack Integration Workflow

### Prerequisites
1. Slack workspace with admin access
2. Slack app created with slash command configured

### Slack App Setup

1. **Create Slack App:**
   - Go to https://api.slack.com/apps
   - Click **"Create New App"** → **"From scratch"**
   - App Name: **"Uderia Assistant"**
   - Workspace: Your workspace

2. **Create Slash Command:**
   - Navigate: **Features → Slash Commands**
   - Click **"Create New Command"**
   - Configure:
     ```
     Command: /uderia
     Request URL: https://n8n.uderia.com/webhook/uderia-slack
     Short Description: Ask questions via Uderia
     Usage Hint: [your question]
     ```
   - Click **"Save"**

3. **Install App to Workspace:**
   - Navigate: **Settings → Install App**
   - Click **"Install to Workspace"**
   - Authorize permissions

### n8n Workflow Import

1. **Import Workflow:**
   - New workflow → Import from File
   - Select: `docs/n8n/workflows/slack-integration.json`

2. **Configure Credentials:**
   - Assign "Uderia API Token" to:
     - Create Session
     - Submit Query
     - Poll Task Status
   - **Note:** No Slack credential needed (uses webhook)

3. **Get Webhook URL:**
   - Click on **"Slack Command Webhook"** node
   - Copy the **"Webhook URL"** (shows at top when node is selected)
   - Example: `https://n8n.uderia.com/webhook/uderia-slack`

4. **Update Slack Command:**
   - Go back to Slack App settings
   - **Slash Commands** → Edit `/uderia`
   - Update **Request URL** with the webhook URL from Step 3
   - Save changes

5. **Save & Activate:**
   - Save workflow in n8n
   - Toggle **"Active"** switch

### Testing

1. **In Slack:**
   - Type: `/uderia Show me all databases`
   - Should see: "⏳ Processing your query..."
   - Wait 5-10 seconds
   - Result posted to channel

2. **Test Error Handling:**
   - Empty query: `/uderia`
   - Should see: "Please provide a question..."

3. **Check n8n Executions:**
   - Monitor **"Executions"** tab in n8n
   - Each Slack command creates an execution
   - View logs if issues occur

---

## Troubleshooting

### Workflow Import Fails

**Issue:** JSON import error
**Solution:**
- Verify JSON file is not corrupted
- Download fresh copy from repository
- Use text editor to check for syntax errors

### Credential Assignment Fails

**Issue:** "Credential not found" error
**Solution:**
- Ensure "Uderia API Token" credential exists
- Check credential name matches exactly
- Recreate credential if needed

### 401 Unauthorized Errors

**Issue:** All HTTP requests fail with 401
**Solution:**
```bash
# Regenerate Uderia access token
curl -X POST 'http://localhost:5050/api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | jq -r '.token'

JWT="eyJ..."

curl -X POST 'http://localhost:5050/api/v1/auth/tokens' \
  -H "Authorization: Bearer $JWT" \
  -d '{"name":"n8n New","expires_in_days":90}' | jq -r '.token'

# Update n8n credential with new token
```

### Polling Timeout

**Issue:** Workflow times out before completion
**Solution:**
- Open **"Initialize Poll State"** node
- Increase `max_polls` value:
  ```javascript
  // Change from 30 to 60
  max_polls: 60
  ```
- Save workflow and re-test

### Email Not Sending (Scheduled Report)

**Issue:** Report execution succeeds but no email
**Solution:**
- Check SMTP credential configuration
- Test SMTP settings outside n8n
- Verify firewall allows SMTP traffic
- Check spam/junk folders
- Review n8n execution logs for SMTP errors

### Slack Command Not Responding

**Issue:** `/uderia` shows "command failed"
**Solution:**
- Verify webhook URL in Slack app matches n8n
- Ensure workflow is **Active** (toggle on)
- Check n8n allows external webhooks
- Test webhook with curl:
  ```bash
  curl -X POST 'https://n8n.uderia.com/webhook/uderia-slack' \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    -d 'text=test&user_name=admin&response_url=https://example.com'
  ```
- Check n8n execution logs

### 400 Bad Request - "No default profile"

**Issue:** Session creation fails
**Solution:**
1. Login to Uderia UI
2. Navigate: **Setup → Profiles**
3. Select any profile
4. Click **"Set as Default"**
5. Re-test workflow

---

## Validation Checklist

### After Import

- [ ] Workflow imported successfully
- [ ] All nodes visible on canvas
- [ ] No error indicators on nodes
- [ ] Credential assignments complete

### After Configuration

- [ ] "Uderia API Token" credential created
- [ ] Credential assigned to all HTTP nodes
- [ ] Base URLs updated (if not localhost)
- [ ] Email addresses updated (scheduled-report)
- [ ] Webhook URL copied (slack-integration)

### After Testing

- [ ] Manual execution successful
- [ ] Results appear in output panel
- [ ] Token counts present
- [ ] No error nodes triggered
- [ ] Email received (scheduled-report)
- [ ] Slack response posted (slack-integration)

### Production Ready

- [ ] All workflows tested manually
- [ ] Scheduled workflows activated
- [ ] Email notifications working
- [ ] Slack integration responding
- [ ] Monitoring setup complete

---

## Quick Reference

### Workflow Files

| File | Purpose | Nodes | Trigger |
|------|---------|-------|---------|
| simple-query.json | Interactive testing | 14 | Manual |
| scheduled-report.json | Daily reports | 17 | Cron |
| slack-integration.json | Slack commands | 19 | Webhook |

### Required Credentials

| Workflow | Credentials Needed |
|----------|-------------------|
| simple-query | Uderia API Token |
| scheduled-report | Uderia API Token + SMTP |
| slack-integration | Uderia API Token only |

### API Endpoints Used

1. `POST /api/v1/sessions` - Create session
2. `POST /api/v1/sessions/{id}/query` - Submit query
3. `GET /api/v1/tasks/{id}` - Poll results

### Typical Execution Times

- Simple query: 5-10 seconds
- Scheduled report: 10-30 seconds
- Slack integration: 5-15 seconds

---

## Support

**Documentation:**
- [QUICKSTART.md](QUICKSTART.md) - Detailed tutorial
- [API_REFERENCE.md](API_REFERENCE.md) - API documentation
- [WORKFLOW_TEMPLATES.md](WORKFLOW_TEMPLATES.md) - Template details
- [TEST_VALIDATION.md](TEST_VALIDATION.md) - Test results

**Common Issues:**
- Check troubleshooting section above
- Review n8n execution logs
- Verify Uderia server is running
- Confirm default profile is set

**Community:**
- n8n Community: https://community.n8n.io
- n8n Documentation: https://docs.n8n.io

---

**Deployment Guide Version:** 1.0
**Last Updated:** 2026-02-09
