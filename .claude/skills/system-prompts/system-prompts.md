# System Prompts Management

Quick reference for locating and encrypting Uderia's system prompts.

## Prompt Locations

### Source Files (Unencrypted)
```
/Users/livin2rave/my_private_code/trusted-data-agent-license/default_prompts/
├── WORKFLOW_META_PLANNING_PROMPT.txt        # Strategic planning
├── WORKFLOW_TACTICAL_PROMPT.txt             # Tactical tool selection
├── CONVERSATION_EXECUTION.txt               # LLM-only execution
├── CONVERSATION_WITH_TOOLS_EXECUTION.txt    # LLM with tools
├── RAG_FOCUSED_EXECUTION.txt                # Knowledge retrieval
├── GENIE_COORDINATOR_PROMPT.txt             # Multi-profile coordination
├── TACTICAL_SELF_CORRECTION_PROMPT*.txt     # Error recovery
├── MASTER_SYSTEM_PROMPT.txt                 # Base system prompt
└── ... (17 prompts total)
```

### Encrypted Database File
```
/Users/livin2rave/my_private_code/uderia/schema/default_prompts.dat
```
**This is what the application loads at runtime.**

## Encryption Workflow

### When to Re-encrypt

Re-encrypt prompts after:
- Editing any `.txt` file in `default_prompts/`
- Reverting prompt changes
- Updating prompt versions

### Encryption Steps

```bash
# 1. Navigate to license directory
cd /Users/livin2rave/my_private_code/trusted-data-agent-license

# 2. Run encryption script
python encrypt_default_prompts.py
```

**Output:**
```
✓ Loaded 17 prompts
✓ Bootstrap key derived successfully
✓ Encrypted: [lists all prompts]
✓ Successfully saved to /Users/livin2rave/my_private_code/schema/default_prompts.dat
  File size: ~96KB
```

### Critical: Verify Output Path

**Common Issue:** Encryption script may save to wrong directory.

**Expected path:**
```
/Users/livin2rave/my_private_code/uderia/schema/default_prompts.dat
```

**Wrong path (if happens):**
```
/Users/livin2rave/my_private_code/schema/default_prompts.dat  ❌ Missing 'uderia'
```

**Fix:**
```bash
# Copy to correct location
cp /Users/livin2rave/my_private_code/schema/default_prompts.dat \
   /Users/livin2rave/my_private_code/uderia/schema/default_prompts.dat

# Remove incorrectly placed file
rm /Users/livin2rave/my_private_code/schema/default_prompts.dat
```

### Apply Changes

```bash
# Restart application to load new prompts
pkill -f "python -m trusted_data_agent.main"

cd /Users/livin2rave/my_private_code/uderia
python -m trusted_data_agent.main
```

## Encryption Architecture

### Two-Tier Encryption

1. **Bootstrap Encryption:**
   - Uses `tda_keys/public_key.pem`
   - Encrypts prompts for initial storage in `.dat` file

2. **Database Re-encryption:**
   - On first app start, prompts decrypted from `.dat`
   - Re-encrypted with tier-specific keys (from license)
   - Stored in `tda_auth.db` → `prompts` table

### Access Control

| Tier | Runtime Decryption | UI Editing |
|------|-------------------|------------|
| User | ✅ Yes | ❌ No |
| Developer | ✅ Yes | ❌ No |
| PE/Enterprise | ✅ Yes | ✅ Yes |

**Runtime:** All tiers can decrypt for LLM conversations
**UI:** Only PE/Enterprise can view/edit via System Prompts panel

## Editing Prompts

### Option 1: Direct File Edit (All Tiers)

```bash
# 1. Edit source file
nano /Users/livin2rave/my_private_code/trusted-data-agent-license/default_prompts/WORKFLOW_META_PLANNING_PROMPT.txt

# 2. Re-encrypt
cd /Users/livin2rave/my_private_code/trusted-data-agent-license
python encrypt_default_prompts.py

# 3. Verify path (fix if needed)
ls -lh /Users/livin2rave/my_private_code/uderia/schema/default_prompts.dat

# 4. Restart app
pkill -f "python -m trusted_data_agent.main"
cd /Users/livin2rave/my_private_code/uderia
python -m trusted_data_agent.main
```

### Option 2: UI Editor (PE/Enterprise Only)

1. Navigate to: **Setup → System Prompts**
2. Select prompt from dropdown
3. Edit in Monaco editor
4. Click **Save**
5. Changes saved to database (`prompts` table)
6. Version history tracked in `prompt_versions`

## Backup Strategy

### Before Major Changes

```bash
# Backup individual prompt
cp /Users/livin2rave/my_private_code/trusted-data-agent-license/default_prompts/WORKFLOW_META_PLANNING_PROMPT.txt \
   /Users/livin2rave/my_private_code/trusted-data-agent-license/default_prompts/WORKFLOW_META_PLANNING_PROMPT.txt.backup

# Or backup entire directory
cp -r /Users/livin2rave/my_private_code/trusted-data-agent-license/default_prompts/ \
      /Users/livin2rave/my_private_code/trusted-data-agent-license/default_prompts_backup_$(date +%Y%m%d)
```

### Restore from Backup

```bash
# Restore single prompt
cp /Users/livin2rave/my_private_code/trusted-data-agent-license/default_prompts/WORKFLOW_META_PLANNING_PROMPT.txt.backup \
   /Users/livin2rave/my_private_code/trusted-data-agent-license/default_prompts/WORKFLOW_META_PLANNING_PROMPT.txt

# Re-encrypt
cd /Users/livin2rave/my_private_code/trusted-data-agent-license
python encrypt_default_prompts.py
```

## Key Prompts Reference

| Prompt | Purpose | Profile Usage |
|--------|---------|---------------|
| `WORKFLOW_META_PLANNING_PROMPT.txt` | Strategic planning | @OPTIM (planner/executor) |
| `WORKFLOW_TACTICAL_PROMPT.txt` | Tool selection per phase | @OPTIM (planner/executor) |
| `CONVERSATION_EXECUTION.txt` | Direct LLM conversation | @IDEAT (llm_only, no tools) |
| `CONVERSATION_WITH_TOOLS_EXECUTION.txt` | LLM with tool calling | @IDEAT (llm_only, useMcpTools=true) |
| `RAG_FOCUSED_EXECUTION.txt` | Knowledge search & synthesis | @FOCUS (rag_focused) |
| `GENIE_COORDINATOR_PROMPT.txt` | Multi-profile orchestration | GENIE (genie) |
| `TACTICAL_SELF_CORRECTION_PROMPT.txt` | Generic error recovery | All tool-enabled profiles |
| `TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR.txt` | Table name fixes | @OPTIM self-correction |
| `TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR.txt` | Column name fixes | @OPTIM self-correction |

## Troubleshooting

### Symptom: Planner not executing (0 LLM calls)

**Likely Cause:** Broken `WORKFLOW_META_PLANNING_PROMPT.txt`

**Fix:**
1. Restore from backup
2. Re-encrypt
3. Restart application

### Symptom: "Prompt not found" errors

**Likely Cause:** Encrypted `.dat` file in wrong location

**Fix:**
```bash
# Check if file exists in correct location
ls -lh /Users/livin2rave/my_private_code/uderia/schema/default_prompts.dat

# If not, check wrong location
ls -lh /Users/livin2rave/my_private_code/schema/default_prompts.dat

# Move to correct location if needed
mv /Users/livin2rave/my_private_code/schema/default_prompts.dat \
   /Users/livin2rave/my_private_code/uderia/schema/default_prompts.dat
```

### Symptom: Changes not taking effect

**Likely Cause:** Application not restarted

**Fix:**
```bash
# Force kill and restart
pkill -f "python -m trusted_data_agent.main"
cd /Users/livin2rave/my_private_code/uderia
python -m trusted_data_agent.main
```

## Related Documentation

- **Architecture:** `docs/Architecture/PROMPT_ENCRYPTION.md`
- **Schema:** `schema/01_core_tables.sql` (prompts table)
- **Loader Code:** `src/trusted_data_agent/agent/prompt_loader.py`
- **Encryption Code:** `src/trusted_data_agent/agent/prompt_encryption.py`

## Quick Commands

```bash
# Check current prompts in database
sqlite3 tda_auth.db "SELECT name, tier_access, LENGTH(content) as size FROM prompts;"

# View prompt content (requires decryption key)
sqlite3 tda_auth.db "SELECT name, content FROM prompts WHERE name='WORKFLOW_META_PLANNING_PROMPT';"

# List all source files
ls -lh /Users/livin2rave/my_private_code/trusted-data-agent-license/default_prompts/*.txt

# Check encrypted file size
ls -lh /Users/livin2rave/my_private_code/uderia/schema/default_prompts.dat
```
