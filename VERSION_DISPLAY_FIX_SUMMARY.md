# Version Display and Decryption Fix Summary

## Issues Fixed

### 1. Version Tag Display
**Problem:** No version information visible in the System Prompt Editor UI.

**Solution:** 
- Added a blue version badge next to the System Prompt Content label
- Badge shows "Version: vX" where X is the current version number
- Badge automatically updates when loading different prompts or switching between base/override
- For overrides, shows the override version (not base version)

**Files Changed:**
- `templates/index.html` - Added `system-prompt-version-badge` element
- `static/js/adminManager.js` - Added logic to populate and show/hide badge
- `src/trusted_data_agent/api/system_prompts_routes.py` - Enhanced GET endpoint to return override version

### 2. Version 1 Decryption Error
**Problem:** Clicking Version 1 causes "Incorrect padding" error because initial migration data was stored as plain text.

**Error:**
```
2025-12-20 10:37:24,912 - quart.app - ERROR - Unexpected error during prompt decryption: Incorrect padding
2025-12-20 10:37:24,912 - quart.app - ERROR - Failed to decrypt version 1 of GOOGLE_MASTER_SYSTEM_PROMPT: Incorrect padding
```

**Root Cause:**
- Version 1 entries created during initial database migration contain plain text content
- Later versions have encrypted content (after encryption was implemented)
- System tried to decrypt plain text, causing "Incorrect padding" error

**Solution:**
- Added graceful fallback in `get_specific_version()` endpoint
- When decryption fails, logs a warning and uses content as plain text
- No longer returns 500 error to user
- Allows both encrypted and plain text versions to coexist

**Files Changed:**
- `src/trusted_data_agent/api/system_prompts_routes.py` - Modified `get_specific_version()` to handle plain text fallback

## Technical Details

### Version Badge Implementation

```html
<span id="system-prompt-version-badge" class="hidden px-2 py-0.5 text-xs font-medium bg-blue-600 text-white rounded">
    Version: <span id="current-version-number">-</span>
</span>
```

```javascript
// Show current version number
const versionBadge = document.getElementById('system-prompt-version-badge');
const versionNumber = document.getElementById('current-version-number');
if (versionBadge && versionNumber && data.metadata?.version) {
    versionNumber.textContent = `v${data.metadata.version}`;
    versionBadge.classList.remove('hidden');
} else if (versionBadge) {
    versionBadge.classList.add('hidden');
}
```

### Decryption Fallback Logic

```python
# Decrypt the content (handle plain text from initial migration)
from trusted_data_agent.agent.prompt_encryption import decrypt_prompt
try:
    decrypted_content = decrypt_prompt(version_row['content'], loader._decryption_key)
except Exception as e:
    app_logger.warning(f"Decryption failed for version {version_number} of {prompt_name}: {e}")
    # Version might be plain text (initial migration data)
    app_logger.info(f"Attempting to use version {version_number} as plain text")
    decrypted_content = version_row['content']
```

### Override Version Detection

Enhanced the GET endpoint to check for user-level and profile-level overrides:

```python
# Check for user-level override first (highest priority)
cursor.execute("""
    SELECT version FROM prompt_overrides 
    WHERE prompt_id = ? AND user_uuid = ? AND is_active = 1
""", (metadata['id'], user_uuid))
override_row = cursor.fetchone()

if override_row:
    has_override = True
    override_version = override_row[0]
else:
    # Check for profile-level override
    cursor.execute("""
        SELECT po.version FROM prompt_overrides po
        JOIN profile_prompt_assignments ppa ON po.id = ppa.override_id
        WHERE po.prompt_id = ? AND ppa.user_uuid = ? AND po.is_active = 1
        LIMIT 1
    """, (metadata['id'], user_uuid))
    profile_override_row = cursor.fetchone()
    if profile_override_row:
        has_override = True
        override_version = profile_override_row[0]

# Use override version if available, otherwise base version
if override_version:
    metadata['version'] = override_version
```

## Testing

Run the test suite:

```bash
conda activate tda
python test_version_display_and_decrypt.py
```

### Manual Verification Checklist

**Version Badge Display:**
1. ✅ Load admin panel → System Prompts tab
2. ✅ Select any prompt from dropdown
3. ✅ Verify blue "Version: vX" badge appears next to "System Prompt Content" label
4. ✅ Edit and save the prompt (creating an override)
5. ✅ Verify version number increments
6. ✅ Verify both orange "Custom Override" and blue "Version: vX" badges show

**Version History Click (No More Errors):**
1. ✅ Expand "Version History" section
2. ✅ Click on Version 1
3. ✅ Verify NO "Incorrect padding" error appears in logs or UI
4. ✅ Verify preview dialog shows the version content
5. ✅ Click "Load This Version" to confirm it loads into editor
6. ✅ Repeat for other versions (v2, v3, etc.)

**Override Version Display:**
1. ✅ Create an override by editing and saving a base prompt
2. ✅ Verify version badge shows override version (should increment from base)
3. ✅ Click "Reset to Default"
4. ✅ Verify version badge reverts to base version
5. ✅ Verify "Custom Override" badge disappears

## Database Schema Reference

Relevant tables:
- `prompts` - Base prompts with `version` column
- `prompt_overrides` - User/profile overrides with their own `version` column
- `prompt_versions` - Historical snapshots with `content` that may be plain text (v1) or encrypted (v2+)

Version tracking:
- Base prompt: `prompts.version` increments on direct updates (rare)
- Override: `prompt_overrides.version` increments on each save
- History: `prompt_versions.version` creates snapshot on each change

## Known Behaviors

1. **Version 1 is plain text** - Initial migration data stored unencrypted
2. **Version 2+ are encrypted** - All saves after encryption implementation use Fernet
3. **Override versions are independent** - Override has its own version counter, not tied to base
4. **Version badge shows active version** - For overrides, shows override version; otherwise shows base version

## Future Enhancements

Consider these improvements in future updates:

1. **Re-encrypt Version 1** - Run maintenance script to encrypt all plain text versions
2. **Version comparison** - Add UI to compare any two versions side-by-side
3. **Version rollback** - Add button to directly load and save historical version
4. **Version annotations** - Add notes/tags to versions for better tracking
5. **Version export** - Export specific version as standalone file

## Logs to Monitor

After deploying, watch for these log patterns:

✅ **Good (expected):**
```
INFO - Attempting to use version 1 as plain text
INFO - System prompt override saved: GOOGLE_MASTER_SYSTEM_PROMPT (user-level)
INFO - Cleared 3 cached entries for GOOGLE_MASTER_SYSTEM_PROMPT
```

❌ **Bad (should not appear):**
```
ERROR - Failed to decrypt version X of PROMPT_NAME: Incorrect padding
ERROR - Unexpected error during prompt decryption: Incorrect padding
```

If you still see decryption errors after this fix, it likely means:
1. The decryption key changed between versions
2. Content was corrupted in database
3. A new encryption bug was introduced

## Files Modified

1. **src/trusted_data_agent/api/system_prompts_routes.py**
   - `get_system_prompt()` - Added override version detection
   - `get_specific_version()` - Added plain text fallback for decryption failures

2. **templates/index.html**
   - Added `system-prompt-version-badge` and `current-version-number` elements

3. **static/js/adminManager.js**
   - Added version badge population logic in prompt loading

4. **test_version_display_and_decrypt.py** (NEW)
   - Automated tests for version display and decryption
   - Manual verification checklist
