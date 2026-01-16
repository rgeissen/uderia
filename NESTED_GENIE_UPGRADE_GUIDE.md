# Nested Genie Coordination - Upgrade Guide

## Overview

This guide covers enabling nested Genie coordination in Uderia, allowing Genie profiles to coordinate other Genie profiles as children. This creates multi-level AI orchestration with built-in safeguards against circular dependencies and infinite recursion.

## Features

✅ **Nested Coordination**: Genie profiles can coordinate other Genie profiles
✅ **Circular Dependency Detection**: Prevents A → B → A cycles at validation time
✅ **Self-Reference Protection**: Cannot select itself as a child
✅ **Depth Limits**: Configurable maximum nesting depth (default: 3)
✅ **Runtime Safeguards**: Depth checks prevent execution beyond limits
✅ **Visual Indicators**: UI shows nested Genies with 🔮 icon and warnings
✅ **Admin Control**: Configure max depth via Administration panel

---

## Installation Type

### 🆕 New Installations

**No action required!** Nested Genie support is automatically enabled when you:

1. Install Uderia from scratch
2. Run the application for the first time
3. Database schema automatically includes all necessary tables and settings

**Default Configuration:**
- Max Nesting Depth: 3 levels
- Self-reference: Blocked
- Circular dependencies: Auto-detected

---

### 🔄 Existing Installations

**You need to run the update script** to enable nested Genie support on existing databases.

#### Prerequisites

- Uderia application stopped
- Backup of `tda_auth.db` (recommended)
- Python environment activated

#### Update Steps

**1. Backup your database (IMPORTANT):**

```bash
# From project root
cp tda_auth.db tda_auth.db.backup.$(date +%Y%m%d_%H%M%S)
```

**2. Run the update script:**

```bash
# From project root
python maintenance/update_nested_genie_support.py
```

**3. Review the output:**

The script will:
- Check current database state
- Add `nesting_level` column to `genie_session_links` table
- Add `maxNestingDepth` setting to `genie_global_settings` table
- Create necessary indexes
- Backfill existing records with default values

**Expected output:**

```
============================================================
NESTED GENIE SUPPORT - DATABASE UPDATE
============================================================

This script updates existing Uderia installations to support
nested Genie coordination (Genie profiles as children).

Features enabled:
  • Genie profiles can coordinate other Genie profiles
  • Circular dependency detection prevents infinite loops
  • Configurable maximum nesting depth (default: 3)
  • Self-reference protection (cannot select itself)
  • Runtime depth checks prevent excessive nesting

============================================================

Proceed with database update? (yes/no): yes

📊 Updating database at: /path/to/tda_auth.db

🔍 Checking current database state...

📝 Adding nesting_level column to genie_session_links...
📝 Adding maxNestingDepth to genie_global_settings...

============================================================
✅ DATABASE UPDATE SUCCESSFUL
============================================================

Changes applied:
  ✅ Added nesting_level column with index
  ✅ Added maxNestingDepth global setting (default: 3)

Nested Genie coordination is now enabled!

Next steps:
  1. Restart the Uderia application
  2. Navigate to Administration → Expert Settings → Genie Coordination
  3. Configure maxNestingDepth (default: 3, range: 1-10)
  4. Edit Genie profiles to add other Genies as children

Warning: Nested Genies significantly increase token usage.
         Circular dependencies and self-reference are blocked automatically.
```

**4. Restart Uderia:**

```bash
python -m trusted_data_agent.main
```

**5. Verify in Admin Panel:**

- Navigate to **Administration → Expert Settings → Genie Coordination**
- Confirm "Max Nesting Depth" setting is visible (default: 3)
- Test by creating a nested Genie configuration (see Usage section below)

---

## Configuration

### Global Settings

Configure nested Genie behavior via **Administration → Expert Settings → Genie Coordination**:

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| **Max Nesting Depth** | 3 | 1-10 | Maximum levels of Genie nesting allowed |
| **Lock** | Unchecked | - | Lock to enforce globally (prevent profile overrides) |

**Recommended values:**
- **3 levels**: Balanced (Master → Worker → Specialist)
- **2 levels**: Conservative (Master → Worker only)
- **4-5 levels**: Advanced use cases (significantly higher token costs)

### Profile-Level Overrides

Individual Genie profiles can override global settings (unless locked):

1. Edit Genie profile
2. Configure `genieConfig` section
3. Add parameter overrides (optional):
   - `temperature`
   - `queryTimeout`
   - `maxIterations`

**Note:** `maxNestingDepth` cannot be overridden at profile level - it's always global.

---

## Usage

### Creating a Nested Genie Hierarchy

**Example: 3-Level Coordinator**

```
PARENT (Genie)
├── ANALYST (Genie)
│   ├── SQL_EXPERT (Efficiency Focused)
│   └── DATA_VALIDATOR (Efficiency Focused)
└── WRITER (Conversation Focused)
```

**Step 1:** Create base profiles (if not already existing)

1. **SQL_EXPERT** (Efficiency Focused)
   - MCP Server: Your database MCP
   - Tools: SQL query tools

2. **DATA_VALIDATOR** (Efficiency Focused)
   - MCP Server: Your database MCP
   - Tools: Validation tools

3. **WRITER** (Conversation Focused)
   - Simple conversation profile

**Step 2:** Create nested Genie profiles

1. **ANALYST** (Genie)
   - Child Profiles: `SQL_EXPERT`, `DATA_VALIDATOR`
   - Description: "Analyzes data using SQL and validation"

2. **PARENT** (Genie)
   - Child Profiles: `ANALYST`, `WRITER`
   - Description: "Coordinates analysis and report generation"

**Step 3:** Test the hierarchy

Execute a query with `@PARENT`:

```
@PARENT Analyze sales data for Q4 and generate a summary report
```

**Expected flow:**
1. PARENT coordinates the query
2. PARENT invokes ANALYST (nested Genie, level 1)
3. ANALYST invokes SQL_EXPERT (level 2)
4. Results flow back up the hierarchy
5. PARENT invokes WRITER to generate report

---

## UI Features

### Visual Indicators

When selecting child profiles for a Genie:

- **🔮 Icon**: Appears next to Genie profiles
- **"Nested" Badge**: Purple badge identifying nested Genies
- **Purple Highlight**: Genie profiles have distinct background color
- **Warning Banner**: Appears when nested Genies are selected

**Example:**

```
Available Child Profiles:

□ @CHAT        Simple Chat                    (Conversation)
□ @RAG         Knowledge Search               (RAG Focused)
🔮 @ANALYST     Data Analyzer                  (Nested Genie) [Nested]
🔮 @SPECIALIST  Domain Expert                  (Nested Genie) [Nested]

⚠️ Nested Genie Coordination Active
   This Genie will coordinate other Genie profiles, significantly
   increasing token usage. Maximum nesting depth is controlled in
   Administration → Expert Settings → Genie Coordination.
```

### Admin Panel

**Location:** Administration → Expert Settings → Genie Coordination

**Controls:**
- Max Nesting Depth slider (1-10)
- Lock checkbox (enforce globally)
- Help text with usage guidance

---

## Validation & Safeguards

### 1. Self-Reference Prevention

**Blocked:**
```
PARENT (Genie)
└── PARENT (itself) ❌
```

**Error:** "Profile cannot reference themselves as children"

### 2. Circular Dependency Detection

**Blocked:**
```
GENIE_A (Genie)
└── GENIE_B (Genie)
    └── GENIE_A (circular!) ❌
```

**Error:** "Circular dependency detected: @GENIE_A → @GENIE_B → @GENIE_A"

**Algorithm:** Depth-First Search (DFS) with path tracking at validation time

### 3. Depth Limit Enforcement

**Blocked (if max depth = 3):**
```
LEVEL_0 (Genie)
└── LEVEL_1 (Genie)
    └── LEVEL_2 (Genie)
        └── LEVEL_3 (Genie) ❌ (exceeds max depth)
```

**Error:** "Genie nesting exceeds maximum depth of 3 levels"

**Enforced at:**
- Validation time (when saving profile)
- Runtime (when executing nested Genie)

### 4. Runtime Depth Check

If a nested Genie attempts to execute beyond the depth limit:

**Error event emitted:**
```json
{
  "event": "genie_slave_completed",
  "success": false,
  "error": "Cannot invoke nested Genie @LEVEL_4 - would exceed max depth (3)",
  "nesting_level": 4,
  "max_depth": 3
}
```

---

## Token Usage & Performance

### Token Cost Impact

Nested Genies significantly increase token usage due to:
- Multiple LLM calls per level
- Context passed between levels
- Coordination overhead

**Example cost breakdown (3-level hierarchy):**

| Level | Operation | Input Tokens | Output Tokens |
|-------|-----------|--------------|---------------|
| 0 | Parent planning | 8,000 | 500 |
| 1 | Analyst planning | 6,000 | 400 |
| 2 | SQL Expert execution | 3,000 | 200 |
| **Total** | | **17,000** | **1,100** |

**Compared to flat execution:** ~2-3x token usage

### Performance Optimization

**Tips to reduce costs:**

1. **Use nested Genies selectively**: Reserve for complex multi-stage tasks
2. **Optimize depth**: 2-3 levels is usually sufficient
3. **Configure timeouts**: Set `queryTimeout` to prevent runaway execution
4. **Monitor token usage**: Check Administration → Cost Analytics
5. **Use non-Genie children where possible**: Mix Genies with Efficiency Focused profiles

---

## Troubleshooting

### Issue: Update script fails with "Database locked"

**Solution:**
```bash
# Stop the application
pkill -f "trusted_data_agent"

# Wait 5 seconds
sleep 5

# Retry update
python maintenance/update_nested_genie_support.py
```

### Issue: "maxNestingDepth not found in genie_global_settings"

**Solution:**
```bash
# Manually insert the setting
sqlite3 tda_auth.db "INSERT OR IGNORE INTO genie_global_settings (setting_key, setting_value, is_locked) VALUES ('maxNestingDepth', '3', 0);"

# Restart application
python -m trusted_data_agent.main
```

### Issue: Circular dependency error when there's no cycle

**Diagnosis:**
```bash
# Check profile configuration
sqlite3 tda_auth.db "SELECT id, tag, profile_type FROM profiles WHERE profile_type='genie';"

# Check slave relationships
sqlite3 tda_auth.db "SELECT * FROM profiles WHERE json_extract(config, '$.genieConfig.slaveProfiles') IS NOT NULL;"
```

**Solution:** Verify profile IDs in slave configuration match actual profile IDs

### Issue: Nested Genies not visible in child selector

**Checklist:**
1. Refresh browser (Ctrl+F5 or Cmd+R)
2. Check browser console for JavaScript errors
3. Verify `configurationHandler.js` changes applied (line 4264)
4. Clear browser cache

---

## Database Schema Reference

### Table: `genie_session_links`

Tracks parent-child session relationships with nesting level.

```sql
CREATE TABLE genie_session_links (
    id INTEGER PRIMARY KEY,
    parent_session_id TEXT NOT NULL,
    slave_session_id TEXT NOT NULL,
    slave_profile_id TEXT NOT NULL,
    slave_profile_tag TEXT NOT NULL,
    user_uuid TEXT NOT NULL,
    execution_order INTEGER DEFAULT 0,
    nesting_level INTEGER DEFAULT 0,  -- NEW: Hierarchy depth
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_genie_nesting_level ON genie_session_links(nesting_level);
```

### Table: `genie_global_settings`

Global configuration for Genie coordination.

```sql
INSERT INTO genie_global_settings (setting_key, setting_value, is_locked) VALUES
    ('temperature', '0.7', 0),
    ('queryTimeout', '300', 0),
    ('maxIterations', '10', 0),
    ('maxNestingDepth', '3', 0);  -- NEW: Max hierarchy depth
```

---

## Rollback Plan

If you need to disable nested Genie support:

### Option 1: UI-Based (Recommended)

1. Set **Max Nesting Depth** to `1` in admin panel
2. **Lock** the setting
3. This effectively disables nesting without code changes

### Option 2: Database-Based

```bash
# Set max depth to 1 (effectively disables nesting)
sqlite3 tda_auth.db "UPDATE genie_global_settings SET setting_value='1', is_locked=1 WHERE setting_key='maxNestingDepth';"
```

### Option 3: Code Revert (Full Rollback)

**Revert these files to previous versions:**
- `src/trusted_data_agent/core/config_manager.py`
- `src/trusted_data_agent/agent/execution_service.py`
- `src/trusted_data_agent/agent/genie_coordinator.py`
- `static/js/handlers/configurationHandler.js`

**Database changes are safe to keep** - they're additive and don't break existing functionality.

---

## Support & Documentation

**Related Documentation:**
- [Genie Profile System](docs/GENIE_PROFILES.md)
- [Admin Panel Guide](docs/ADMIN_PANEL.md)
- [Cost Management](docs/COST_MANAGEMENT.md)

**Implementation Files:**
- Circular dependency detection: [config_manager.py:1169](src/trusted_data_agent/core/config_manager.py#L1169)
- Runtime depth tracking: [execution_service.py:230](src/trusted_data_agent/agent/execution_service.py#L230)
- Nested invocation: [genie_coordinator.py:91](src/trusted_data_agent/agent/genie_coordinator.py#L91)
- UI visual indicators: [configurationHandler.js:4264](static/js/handlers/configurationHandler.js#L4264)

**Questions or Issues?**
- GitHub Issues: https://github.com/anthropics/claude-code/issues
- Internal Documentation: `CLAUDE.md`

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-16 | Initial release: Nested Genie coordination with safeguards |

---

**End of Guide**
