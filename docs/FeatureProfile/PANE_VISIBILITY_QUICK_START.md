# Pane Visibility System - Quick Reference

## What Was Implemented

✅ **Tier-based pane visibility control system** that allows administrators to configure which user tiers can access different panes in the application.

## Default Configuration

| Pane | User | Developer | Admin |
|------|------|-----------|-------|
| **Conversations** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Executions** | ❌ No | ✅ Yes | ✅ Yes |
| **Intelligence** | ❌ No | ✅ Yes | ✅ Yes |
| **Marketplace** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Setup** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Administration** | ❌ No | ❌ No | ✅ Yes |

## Quick Start

### 1. Run Migration (First Time Only)
```bash
python maintenance/migrate_pane_visibility.py
```

### 2. Access Configuration
1. Log in as admin
2. Go to **Administration** → **Pane Configuration** tab
3. Toggle visibility for each tier using the switches
4. Changes apply immediately

### 3. Test Configuration
- Log in with different tier accounts to verify visibility
- Users only see panes they have access to
- No restart required

## Key Features

- **Real-time Updates**: Changes apply immediately via toggle switches
- **Protected Admin Pane**: Administration pane always visible to admins only
- **Reset to Defaults**: One-click reset button with confirmation
- **Audit Logging**: All changes logged with admin user details
- **Responsive UI**: Clean table interface with color-coded tier indicators

## Files Modified/Created

### Backend
- `src/trusted_data_agent/auth/models.py` - Added `PaneVisibility` model
- `src/trusted_data_agent/api/admin_routes.py` - Added 3 new endpoints
- `maintenance/migrate_pane_visibility.py` - Migration script

### Frontend
- `templates/index.html` - Added Pane Configuration tab + visibility logic
- `static/js/adminManager.js` - Added pane management functions

### Documentation
- `docs/PANE_VISIBILITY_CONFIGURATION.md` - Complete feature documentation
- `docs/Docker/DOCKER_CREDENTIAL_ISOLATION.md` - Updated button text

## API Endpoints

```http
GET    /api/v1/admin/panes                    # List all panes
PATCH  /api/v1/admin/panes/<id>/visibility    # Update pane visibility
POST   /api/v1/admin/panes/reset              # Reset to defaults
```

## Database

New table: `pane_visibility`
- Stores visibility flags for each tier
- Auto-initialized with defaults
- Survives application restarts

## Testing Checklist

- [ ] Migration script runs successfully
- [ ] Admin can access Pane Configuration tab
- [ ] Toggle switches update visibility
- [ ] User tier sees only allowed panes
- [ ] Developer tier sees correct panes
- [ ] Admin tier sees all panes
- [ ] Reset to defaults works
- [ ] Changes persist after logout/login
- [ ] Protected admin pane cannot be disabled

## Common Issues

**Panes not hiding?**
→ Hard refresh browser (Ctrl+Shift+R)

**Admin pane not visible?**
→ Verify user has `profile_tier='admin'`

**Migration fails?**
→ Check `TDA_AUTH_ENABLED=true` in environment

## Next Steps

After testing, you can:
1. Adjust default configuration for your use case
2. Create different tier configurations for different deployments
3. Document your custom configuration for team

---

**Full Documentation**: See `docs/PANE_VISIBILITY_CONFIGURATION.md`
