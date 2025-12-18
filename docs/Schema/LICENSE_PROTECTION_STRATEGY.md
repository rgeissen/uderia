# License-Based Prompt Protection Strategy

**Purpose:** Maintain the same licensing functionality when migrating from prompts.dat to database  
**Date:** 2025-12-18  
**Phase:** Phase 2 preparation

---

## Current System (prompts.dat)

### Protection Layers:

1. **License Verification**
   - Validates license.key with public key signature
   - Checks expiration date
   - Stores license info in APP_STATE

2. **Prompt Decryption**
   - Uses `prompt_key` from license payload
   - Fernet encryption on entire prompts.dat file
   - **Key Point:** Without valid license, prompts cannot be decrypted

3. **Tier-Based Overrides**
   - "Prompt Engineer" + "Enterprise" tiers can use prompt_overrides/
   - Overrides loaded AFTER base prompts decrypt

### Security Model:
```
License Valid? → Get prompt_key → Decrypt prompts.dat → Load to memory → Apply tier overrides
     ❌              ❌                  ❌                    ❌               ❌
    (App won't start)
```

---

## New System (Database) - Design Options

### Option 1: ✅ **License-Gated Database Access** (RECOMMENDED)

Store prompts unencrypted in database, but **gate access through license validation**.

**Implementation:**
```python
# In prompt_loader.py (Phase 2)
class PromptLoader:
    def __init__(self):
        # Verify license FIRST (same as current system)
        self._verify_license()
        
        # Only connect to DB if license valid
        self.db_path = self._get_database_path()
        self._license_info = APP_STATE['license_info']
        
    def _verify_license(self):
        """Same license verification as prompts.py"""
        # Check license.key exists
        # Verify signature
        # Check expiration
        # Store in APP_STATE
        # RAISE RuntimeError if invalid
        
    def load_prompt(self, name):
        """Load prompt from database - only works if license valid"""
        # Database already accessible because license was verified in __init__
        return self._query_prompt_from_db(name)
```

**Security Model:**
```
License Valid? → Connect to DB → Query prompts → Apply tier overrides
     ❌              ❌              ❌               ❌
    (App won't start - same as current)
```

**Pros:**
- ✅ Same security level as prompts.dat (app won't run without license)
- ✅ Simple implementation
- ✅ No performance overhead
- ✅ Standard SQLite tools work for debugging

**Cons:**
- ⚠️ Database file readable if accessed directly (but so is tda_auth.db already)
- ⚠️ Relies on file system permissions

---

### Option 2: 🔒 **SQLCipher Encrypted Database**

Encrypt entire tda_auth.db with SQLCipher using license-based key.

**Implementation:**
```python
class PromptLoader:
    def __init__(self):
        self._verify_license()
        
        # Use prompt_key from license to unlock database
        prompt_key = APP_STATE['license_info']['prompt_key']
        self.conn = self._connect_encrypted_db(prompt_key)
        
    def _connect_encrypted_db(self, key):
        import sqlcipher3
        conn = sqlcipher3.connect('tda_auth.db')
        conn.execute(f"PRAGMA key = '{key}'")
        return conn
```

**Security Model:**
```
License Valid? → Get prompt_key → Decrypt DB → Query prompts → Apply tier overrides
     ❌              ❌               ❌            ❌               ❌
    (App won't start + DB encrypted at rest)
```

**Pros:**
- ✅ Database encrypted at rest
- ✅ Same prompt_key mechanism
- ✅ Stronger protection

**Cons:**
- ❌ Requires sqlcipher3 library (new dependency)
- ❌ All database access needs encryption
- ❌ Migration complexity (re-encrypt tda_auth.db)
- ❌ Must update ALL database connections app-wide
- ❌ Harder to debug

---

### Option 3: 🔐 **Hybrid: Encrypt Only Prompt Content**

Store prompts in database, but encrypt the `content` field using Fernet.

**Implementation:**
```python
# Migration: Encrypt content before inserting
def migrate_with_encryption(prompt_name, content, prompt_key):
    cipher = Fernet(prompt_key)
    encrypted_content = cipher.encrypt(content.encode('utf-8'))
    
    cursor.execute("""
        INSERT INTO prompts (name, content, ...) 
        VALUES (?, ?, ...)
    """, (prompt_name, encrypted_content, ...))

# Loading: Decrypt on retrieval
def load_prompt(self, name):
    prompt_key = APP_STATE['license_info']['prompt_key']
    cipher = Fernet(prompt_key)
    
    encrypted_content = self._query_from_db(name)
    return cipher.decrypt(encrypted_content).decode('utf-8')
```

**Security Model:**
```
License Valid? → Get prompt_key → Query DB → Decrypt content → Apply tier overrides
     ❌              ❌              ✅           ❌                ❌
    (App won't start + prompts encrypted in DB)
```

**Pros:**
- ✅ Prompt content encrypted
- ✅ Same Fernet + prompt_key mechanism
- ✅ No new dependencies
- ✅ Only affects prompt system (not entire DB)

**Cons:**
- ⚠️ Can't query by content (encrypted blob)
- ⚠️ Slightly more complex code
- ⚠️ Metadata (names, descriptions) still visible

---

## Recommendation: **Option 1** (License-Gated Access)

### Reasoning:

1. **Same Security Level**
   - App won't start without valid license
   - License must not be expired
   - Same enforcement as prompts.dat

2. **Simplicity**
   - No encryption overhead
   - Standard SQLite
   - Easy debugging

3. **Consistency**
   - tda_auth.db already stores sensitive data (passwords, API keys, tokens) unencrypted
   - File system permissions protect the database
   - License is the security boundary, not encryption

4. **Practical Security**
   - If attacker has file system access to read tda_auth.db, they already have:
     - User passwords
     - API keys
     - Access tokens
     - Database credentials
   - Encrypting just prompts doesn't add meaningful protection

5. **Phase 2 Focus**
   - Keep implementation simple
   - Can add encryption later (Phase 8) if needed
   - Don't over-engineer early phases

---

## Implementation Plan

### Phase 2: License-Gated Database Access

#### 1. Update `prompt_loader.py` (new file)

```python
"""
Prompt Loader - Database-backed prompt system with license protection
Replaces file-based prompts.dat with database storage while maintaining
the same license verification and tier-based access control.
"""

class PromptLoader:
    def __init__(self):
        """Initialize loader - will raise RuntimeError if license invalid"""
        # Step 1: Verify license (same as prompts.py)
        self._verify_license()
        
        # Step 2: Connect to database (only if license valid)
        self.db_path = self._get_database_path()
        
        # Step 3: Store license info for tier checks
        self._license_info = APP_STATE['license_info']
        
        # Step 4: Initialize cache
        self._cache = {}
        
    def _verify_license(self):
        """
        Verify license.key signature and expiration.
        RAISES RuntimeError if invalid (app won't start).
        
        This is the SECURITY GATE - same as prompts.dat system.
        """
        # [Same logic as prompts.py _verify_license_and_load_prompts]
        pass
```

#### 2. Tier-Based Override System

```python
class PromptLoader:
    def load_prompt(self, name, user_uuid=None, profile_id=None):
        """
        Load prompt with tier-based override hierarchy:
        1. User override (if Prompt Engineer/Enterprise tier)
        2. Profile override (if exists)
        3. Base prompt from database
        """
        tier = self._license_info.get('tier')
        
        # Check user-level override (tier-gated)
        if tier in ['Prompt Engineer', 'Enterprise']:
            user_override = self._get_user_override(name, user_uuid)
            if user_override:
                return user_override
        
        # Check profile-level override
        if profile_id:
            profile_override = self._get_profile_override(name, profile_id)
            if profile_override:
                return profile_override
        
        # Return base prompt
        return self._get_base_prompt(name)
```

#### 3. Migration from prompts.dat

- Keep prompts.dat during transition
- Load from database by default
- Fallback to prompts.dat if database query fails
- Remove prompts.dat in Phase 3 or 4

---

## Tier-Based Feature Matrix

| Feature | Standard | Prompt Engineer | Enterprise |
|---------|----------|-----------------|------------|
| Use prompts | ✅ | ✅ | ✅ |
| View prompts | ✅ | ✅ | ✅ |
| Edit prompts | ❌ | ✅ | ✅ |
| Create prompts | ❌ | ✅ | ✅ |
| Delete prompts | ❌ | ❌ | ✅ |
| Manage parameters | ❌ | ✅ | ✅ |
| User overrides | ❌ | ✅ | ✅ |
| Profile overrides | ❌ | ✅ | ✅ |

---

## Security Checklist

- [ ] License verification MUST happen in `__init__` (before DB access)
- [ ] Invalid license MUST raise RuntimeError (app won't start)
- [ ] Expired license MUST be rejected
- [ ] Tier info MUST be stored from license payload
- [ ] Override access MUST check tier (Prompt Engineer/Enterprise only)
- [ ] File system permissions MUST protect tda_auth.db (same as now)
- [ ] Database path MUST be in protected directory (project root)

---

## Future Enhancements (Optional - Phase 8+)

If stronger protection needed later:

1. **Add SQLCipher** (Option 2)
   - Encrypt entire database
   - Use prompt_key from license
   - Requires app-wide database connection updates

2. **Add Content Encryption** (Option 3)
   - Encrypt only prompt content fields
   - Use Fernet + prompt_key
   - Simpler than full DB encryption

3. **Add Usage Tracking**
   - Log prompt access by user
   - Detect unauthorized access attempts
   - Audit trail in database

---

## Next Steps

1. Implement `prompt_loader.py` in Phase 2 with Option 1
2. Test license verification (valid, invalid, expired)
3. Test tier-based override access
4. Verify app won't start without license (same as current)
5. Document for Phase 3 (when prompts.dat can be removed)

---

**Decision:** Use **Option 1 - License-Gated Database Access**  
**Rationale:** Same security level, simpler implementation, consistent with existing tda_auth.db  
**Status:** Ready for Phase 2 implementation
