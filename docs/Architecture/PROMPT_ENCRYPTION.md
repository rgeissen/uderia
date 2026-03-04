# License-Based Prompt Encryption System

## Overview

The Uderia prompt encryption system provides tier-based access control to system prompts through a multi-layered encryption architecture. This ensures intellectual property protection while allowing legitimate licensed users to access and modify prompts based on their license tier.

## Architecture

### Security Layers

1. **Distribution Layer** - Default prompts encrypted for distribution
   - Encrypted with key derived from `public_key.pem`
   - Stored in `schema/default_prompts.dat`
   - Can be decrypted during bootstrap by any installation

2. **Database Layer** - Prompts re-encrypted with license-tier keys
   - Stored encrypted in `tda_auth.db`
   - Requires valid PE/Enterprise license to decrypt
   - Different licenses produce different decryption keys

3. **Runtime Layer** - In-memory caching after decryption
   - Decrypted content cached after license validation
   - Access control enforced on every request
   - Placeholder content shown for unauthorized tiers

### License Tiers

| Tier | Runtime LLM Usage | UI View/Edit | Override Creation | Database Visibility |
|------|-------------------|--------------|-------------------|---------------------|
| **Standard** | ✅ Can decrypt for LLM | ❌ Denied | ❌ No | Encrypted only |
| **Prompt Engineer** | ✅ Can decrypt for LLM | ✅ Full Access | ✅ Profile-level | Decrypted |
| **Enterprise** | ✅ Can decrypt for LLM | ✅ Full Access | ✅ User & Profile | Decrypted |

**Note**: All tiers can decrypt system prompts for LLM conversations (runtime usage). Only Prompt Engineer and Enterprise tiers can view/edit prompt content in the UI.

## Encryption Flow

### 1. Prompt Creation (Development Time)

```bash
# 1. Edit plain text prompt files
cd trusted-data-agent-license/default_prompts/
vim WORKFLOW_META_PLANNING_PROMPT.txt  # (or any .txt file)

# 2. Generate encrypted distribution file
cd ..
python encrypt_default_prompts.py  # Reads default_prompts/*.txt, writes to uderia/schema/

# 3. Commit the encrypted artifact
cd ../uderia
git add schema/default_prompts.dat
git commit -m "Updated system prompts"
```

**Output**: `schema/default_prompts.dat` (~86KB encrypted JSON, 15 prompts)

### 2. Bootstrap (First Application Start)

```python
# In database.py::_bootstrap_prompt_system()

1. Load default_prompts.dat
2. Decrypt with bootstrap key (from public_key.pem)
3. Re-encrypt with PE/Enterprise tier key
4. Store encrypted in database
```

**Result**: Database contains encrypted prompts that only PE/Enterprise licenses can decrypt

### 3. Runtime Access

```python
# In prompt_loader.py::get_prompt()

1. Load encrypted content from database
2. Derive decryption key from license signature + tier
3. Decrypt prompt content for LLM usage (ALL tiers)
4. Cache decrypted content in memory
5. UI access control enforced separately via can_access_prompts_ui()
```

**Changed Behavior**: Standard tier users can now decrypt prompts for LLM conversations. The restriction on viewing/editing prompts is enforced at the UI level only.

## Key Derivation

### Bootstrap Key (Distribution)

```python
def derive_bootstrap_key():
    """Derived from public_key.pem (shipped with app)"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        salt=b'uderia_bootstrap_prompts_v1',
        iterations=100_000
    )
    return kdf.derive(public_key_bytes)
```

- **Purpose**: Protect prompts during distribution
- **Security**: Anyone with source can decrypt (IP protection only)
- **Used**: Only during bootstrap process

### Tier Key (Database Storage)

```python
def derive_tier_key(license_info):
    """Derived from license signature + tier"""
    key_material = f"{signature}:{tier}:uderia_prompt_encryption_v1"
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        salt=b'uderia_tier_prompts_v1',
        iterations=100_000
    )
    return kdf.derive(key_material)
```

- **Purpose**: License-specific database encryption
- **Security**: Requires valid license file to decrypt
- **Used**: Runtime decryption from database

## Files Modified/Created

### Key Files

1. **`src/trusted_data_agent/agent/prompt_encryption.py`** (~236 lines)
   - Core encryption utilities
   - Key derivation functions (bootstrap + tier)
   - Access control checks (`can_access_prompts_ui`, `can_access_prompts`)
   - Re-encryption helper for bootstrap→tier conversion

2. **`trusted-data-agent-license/encrypt_default_prompts.py`** (~173 lines)
   - Bootstrap encryption script (lives in the **license repo**, not `schema/`)
   - Reads `.txt` files from `default_prompts/` directory
   - Generates `schema/default_prompts.dat` in the uderia repo

3. **`trusted-data-agent-license/update_prompt.py`** (~547 lines)
   - Zero-downtime prompt deployment to existing installations
   - See [Deploying Prompt Updates](#deploying-prompt-updates-to-existing-installations) below

4. **`schema/default_prompts.dat`** (~86KB)
   - 15 encrypted prompts
   - JSON format (base64-encoded Fernet tokens)
   - Distributed with application

5. **`schema/test_prompt_encryption.py`**
   - Comprehensive test suite
   - All tests passing

### Modified Files

1. **`src/trusted_data_agent/agent/prompt_loader.py`**
   - Added `derive_tier_key` import
   - Added `_can_decrypt` and `_decryption_key` attributes
   - Modified `_load_with_overrides()` to decrypt prompts
   - Added decryption for user/profile overrides

2. **`src/trusted_data_agent/auth/database.py`**
   - Modified `_bootstrap_prompt_system()`
   - Loads `default_prompts.dat`
   - Decrypts with bootstrap key
   - Re-encrypts with tier key for database

## Usage

### For Developers

**Update Default Prompts (for new installations)**:
```bash
# 1. Edit plain text prompt files in the license repo
cd trusted-data-agent-license/default_prompts/
vim WORKFLOW_META_PLANNING_PROMPT.txt

# 2. Regenerate encrypted distribution file
cd ..
python encrypt_default_prompts.py

# 3. Commit the encrypted artifact in the uderia repo
cd ../uderia
git add schema/default_prompts.dat
git commit -m "Updated system prompts"
```

**Deploy to Existing Installations (zero-downtime)**:
```bash
cd trusted-data-agent-license
python update_prompt.py --app-root /path/to/uderia --all
```

**Test Encryption System**:
```bash
cd uderia/schema
python test_prompt_encryption.py
```

### For End Users

**First Installation**:
1. Delete old `tda_auth.db` (if upgrading)
2. Place `license.key` in `tda_keys/` folder
3. Start application - database auto-bootstraps
4. Prompts encrypted in database

**Runtime**:
- **All Tiers**: Can decrypt prompts for LLM conversations (runtime usage)
- **Standard Tier**: Cannot view/edit prompts in the System Prompts UI editor
- **PE/Enterprise**: Full prompt access — can view/edit through UI

## Security Considerations

### Protection Model

✅ **What This Protects Against**:
- Casual inspection of prompt intellectual property
- Unauthorized access by Standard tier users
- Database dumps revealing prompt strategies
- Accidental disclosure through logs/errors

❌ **What This Does NOT Protect Against**:
- Determined attacker with source code access
- Memory dumps during runtime (decrypted content in RAM)
- License file sharing (same license = same decryption key)
- Reverse engineering of encryption implementation

### Best Practices

1. **License Management**:
   - Issue unique licenses per customer
   - Different licenses produce different keys
   - Revoke/expire licenses through expiration dates

2. **Database Security**:
   - Store `tda_auth.db` with appropriate file permissions
   - Encrypt database file system if needed
   - Regular backups with encryption

3. **Key Management**:
   - Keep `public_key.pem` in repository (required for bootstrap)
   - Never commit `private_key.pem` (license signing only)
   - Rotate keys if compromise suspected

## Troubleshooting

### "Failed to decrypt prompt" Error

**Cause**: License tier changed or database encrypted with different key

**Solution**:
```bash
# Delete database and re-bootstrap
rm tda_auth.db
# Restart application - will auto-create with current license
```

### "Access denied to prompt" Warning

**Cause**: Standard tier license attempting to view/edit prompts in the UI

**Expected**: This is normal — Standard tier can decrypt for LLM runtime but cannot access the System Prompts editor

**Solution**: Upgrade to Prompt Engineer or Enterprise license for UI access

### Prompts Show "[MIGRATE]" Placeholder

**Cause**: `default_prompts.dat` missing during bootstrap

**Solution**:
```bash
# Generate encrypted prompts (from the license repo)
cd trusted-data-agent-license
python encrypt_default_prompts.py

# Delete and re-bootstrap database
cd ../uderia
rm tda_auth.db
# Restart application
```

## Deploying Prompt Updates to Existing Installations

The `update_prompt.py` script (in `trusted-data-agent-license/`) enables **zero-downtime** prompt deployments to running installations.

### Usage

```bash
cd trusted-data-agent-license

# Update a single prompt
python update_prompt.py --app-root /path/to/uderia --prompt WORKFLOW_META_PLANNING_PROMPT

# Update all prompts
python update_prompt.py --app-root /path/to/uderia --all

# List available prompts
python update_prompt.py --list
```

### What It Does

1. Loads source prompts from `default_prompts/*.txt`
2. Compares against existing database content (skips unchanged — idempotent)
3. Encrypts changed prompts with the installation's tier key
4. Increments version numbers (audit trail in `prompt_versions` table)
5. Syncs global parameters from `tda_config.json`
6. Syncs profile prompt mappings
7. Invalidates runtime cache via `POST /v1/admin/prompts/clear-cache` (JWT-authenticated)

### When to Use

| Scenario | `update_prompt.py` | `encrypt_default_prompts.py` |
|----------|:-------------------:|:----------------------------:|
| Update prompts for **new** installations | | Yes |
| Update prompts on **existing** customers | Yes | |
| Customer license tier upgrade | Yes | |
| Re-encrypt with new license key | Yes | |

For full details, see the `system-prompts` skill or CLAUDE.md.

---

## Prompt File Inventory

All source prompts live in `trusted-data-agent-license/default_prompts/` as plain `.txt` files:

| Prompt | Category | Description |
|--------|----------|-------------|
| `MASTER_SYSTEM_PROMPT.txt` | System | Core agent persona (OpenAI/Anthropic) |
| `GOOGLE_MASTER_SYSTEM_PROMPT.txt` | System | Variant for Google Gemini |
| `OLLAMA_MASTER_SYSTEM_PROMPT.txt` | System | Variant for Ollama local models |
| `WORKFLOW_META_PLANNING_PROMPT.txt` | Planning | Strategic multi-phase plan decomposition |
| `WORKFLOW_TACTICAL_PROMPT.txt` | Planning | Per-phase tool selection |
| `TASK_CLASSIFICATION_PROMPT.txt` | Planning | Aggregation vs synthesis classification |
| `ERROR_RECOVERY_PROMPT.txt` | Error Handling | Multi-step plan failure recovery |
| `TACTICAL_SELF_CORRECTION_PROMPT.txt` | Error Handling | Single tool call correction |
| `TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR.txt` | Error Handling | Column-not-found recovery |
| `TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR.txt` | Error Handling | Table-not-found recovery |
| `SQL_CONSOLIDATION_PROMPT.txt` | Optimization | SQL query consolidation |
| `CONVERSATION_EXECUTION.txt` | Execution | `llm_only` profile (no tools) |
| `CONVERSATION_WITH_TOOLS_EXECUTION.txt` | Execution | `llm_only` profile with MCP tools |
| `GENIE_COORDINATOR_PROMPT.txt` | Execution | `genie` multi-profile coordination |
| `RAG_FOCUSED_EXECUTION.txt` | Execution | `rag_focused` semantic search |

---

## License Repo Scripts

The `trusted-data-agent-license/` repository contains these infrastructure scripts:

| Script | Purpose |
|--------|---------|
| `generate_keys.py` | One-time RSA-4096 keypair generation |
| `generate_license.py` | Create signed license files for customers |
| `encrypt_default_prompts.py` | Generate `schema/default_prompts.dat` for distribution |
| `update_prompt.py` | Deploy prompt changes to existing installations |

### Related Documentation (in the license repo)

- `docs/Prompt_Engineering_Manual.md` — User guide for PE/Enterprise prompt editors
- `docs/Owners_Manual_Secret_Management_Licensing.md` — System admin guide for keys, licenses, deployment
- `docs/Frontend_Developer_Guide_License_Tiers.md` — UI integration guide for tier-based access

---

## Performance

- **Bootstrap**: ~2-3 seconds for 15 prompts (one-time cost)
- **Runtime Decryption**: <10ms per prompt (cached after first load)
- **Memory Overhead**: ~500KB for cached decrypted prompts
- **Database Size**: Encrypted prompts add ~100KB to database

## Migration from Old System

### From prompts.dat (Fernet)

Old system used single symmetric key (`prompt_key.txt`) for all users.

**Migration Steps**:
1. Run `encrypt_default_prompts.py` to create new encrypted distribution
2. Delete old `tda_auth.db`
3. Restart application - auto-bootstraps with new encryption
4. Old `prompts.dat` no longer used

### Key Differences

| Aspect | Old System | New System |
|--------|------------|------------|
| Storage | File (`prompts.dat`) | Database (`tda_auth.db`) |
| Key | Single key for all | License-specific keys |
| Access | All users equal | Tier-based restrictions |
| Distribution | Encrypted file | Encrypted file → DB |
| Modifications | File replacement | UI-based editing |

## API Reference

### prompt_encryption.py

```python
derive_bootstrap_key() -> bytes
    """Derive key from public_key.pem for bootstrap"""

derive_tier_key(license_info: Dict) -> bytes
    """Derive key from license signature + tier"""

encrypt_prompt(content: str, key: bytes) -> str
    """Encrypt prompt content"""

decrypt_prompt(encrypted: str, key: bytes, silent_fail: bool = False) -> str
    """Decrypt prompt content. silent_fail suppresses ERROR logs for plain text fallback."""

re_encrypt_prompt(encrypted: str, old_key: bytes, new_key: bytes) -> str
    """Re-encrypt from bootstrap key to tier key (used during bootstrap)"""

can_access_prompts(tier: str) -> bool
    """DEPRECATED: Always returns True. Use can_access_prompts_ui() instead."""

can_access_prompts_ui(tier: str) -> bool
    """Check if tier can view/edit prompts in the UI (PE/Enterprise only)"""

get_placeholder_content(tier: str) -> str
    """Get placeholder for unauthorized UI access"""
```

### prompt_loader.py

```python
class PromptLoader:
    def get_prompt(self, name: str, user_uuid=None, profile_id=None, 
                   parameters=None) -> str:
        """Load and decrypt prompt with tier checking"""
    
    @property
    def _can_decrypt -> bool:
        """Whether current license can decrypt prompts"""
    
    @property
    def _decryption_key -> bytes:
        """License-derived decryption key"""
```

## Future Enhancements

Potential improvements for future versions:

1. **Asymmetric Encryption**: RSA public/private key pairs per tier
2. **Prompt Versioning**: Encrypted version history with audit trail
3. **Partial Encryption**: Encrypt sensitive sections only
4. **Hardware Keys**: Support for HSM/TPM-backed encryption
5. **Multi-Tenancy**: Per-tenant encryption keys

## Conclusion

The license-based prompt encryption system successfully balances:
- ✅ Intellectual property protection
- ✅ Tier-based access control
- ✅ Developer workflow simplicity
- ✅ Runtime performance
- ✅ Database security

This architecture ensures that only authorized users with valid PE/Enterprise licenses can access the strategic prompt content that powers the application's intelligence.
