# Banner Messaging System

TDA has **two distinct banner systems** for displaying messages to users.

## 1. Application-Level Banner

**Location:** Top navigation bar (next to "Uderia Platform" title and GitHub star)

**Element ID:** `header-status-message`

**Usage:**
```javascript
// Import the function
import { showAppBanner } from './bannerSystem.js';

// Or use global function (after bannerSystem.js is loaded)
showAppBanner('Operation successful!', 'success');
showAppBanner('Something went wrong', 'error', 3000); // 3 second duration
```

**When to use:**
- ✅ Global configuration changes
- ✅ Authentication/authorization messages
- ✅ RAG operations (create/delete collections)
- ✅ Admin operations (user management, system settings)
- ✅ Credential management
- ✅ Access token management
- ✅ MCP server operations
- ✅ Profile tier changes
- ✅ System-wide notifications

**Types:** `success` (green), `error` (red), `warning` (yellow), `info` (blue)

---

## 2. Conversation-Level Banner

**Location:** Inside the conversation pane (below profile selector, above chat area)

**Element ID:** `profile-override-warning-banner`

**Usage:**
```javascript
// Import the function
import { showConversationBanner, hideConversationBanner } from './bannerSystem.js';

// Or use global function (after bannerSystem.js is loaded)
showConversationBanner('Profile override active', 'warning', true); // dismissible
hideConversationBanner();
```

**When to use:**
- ✅ Profile override warnings/errors
- ✅ Conversation-specific errors
- ✅ Query submission issues
- ✅ Context/history warnings
- ✅ Session-specific messages
- ✅ Token/context limit warnings
- ✅ Streaming connection issues

**Types:** `success` (green), `error` (red), `warning` (yellow), `info` (blue)

---

## Color Standards

All banners use consistent color coding:
- 🟢 **Success**: Green (`green-600`)
- 🔴 **Error**: Red (`red-600`)
- 🟡 **Warning**: Yellow (`yellow-600`)
- 🔵 **Info**: Blue (`blue-600`)

---

## Quick Decision Guide

**Ask yourself:** "Is this message about the entire application or just this conversation?"

- **Entire application** → Use `showAppBanner()`
  - Examples: "Credentials saved", "User created", "RAG collection deleted"
  
- **This conversation only** → Use `showConversationBanner()`
  - Examples: "Profile override failed", "Query too long", "Connection lost"

---

## API Reference

### showAppBanner(message, type, duration)
- `message` (string): Message to display
- `type` (string): 'success', 'error', 'warning', or 'info' (default: 'info')
- `duration` (number): Display duration in milliseconds (default: 5000)

### showConversationBanner(message, type, dismissible)
- `message` (string): Message to display
- `type` (string): 'success', 'error', 'warning', or 'info' (default: 'warning')
- `dismissible` (boolean): Show close button (default: true)

### hideConversationBanner()
- Hides the conversation-level banner

### hideAppBanner()
- Immediately hides the application-level banner

---

## Visual Distinction

**Application Banner:**
- Position: Fixed at top
- Color: Blue/Green/Orange/Red background
- Auto-hides after 5 seconds
- No dismiss button

**Conversation Banner:**
- Position: Inside conversation pane
- Color: Yellow/Green/Red tinted background
- Can be persistent or dismissible
- Has icon and optional close button

---

## Implementation Files

- **Core System:** `/static/js/bannerSystem.js`
- **HTML Markers:** `/templates/index.html` (search for "BANNER SYSTEM")
- **Usage Examples:** 
  - Application: `/static/js/handlers/accessTokenManager.js`
  - Conversation: Check profile override handlers in conversation code
