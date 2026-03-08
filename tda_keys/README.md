# TDA Keys Directory

This directory contains security keys for the Uderia Platform.

## Included Files (V1.0.0)

### 1. **license.key** - License Validation Key
- **Purpose**: Required for platform startup and tier-based feature access
- **Status**: ✅ **Included** in V1.0.0 distribution
- **Security**: Keep backed up securely (required for all deployments)

### 2. **public_key.pem** - Public Key for Signature Verification
- **Purpose**:
  - Bootstrap encryption (`schema/default_prompts.dat` decryption)
  - License signature verification
- **Status**: ✅ **Included** in V1.0.0 distribution
- **Security**: Required for system operation, safe to distribute

### 3. **jwt_secret.key** - JWT Signing Secret (NOT INCLUDED)
- **Purpose**: Session authentication token signing
- **Status**: ⚠️ **MUST BE GENERATED** on installation
- **Security**: Deployment-specific, never commit to version control

## First-Time Setup (REQUIRED)

After cloning this repository, you **MUST** generate the JWT secret:

```bash
# Navigate to repository root
cd /path/to/uderia

# Generate JWT secret (CRITICAL - run this now!)
python maintenance/regenerate_jwt_secret.py
```

**Expected output:**
```
JWT secret has been regenerated successfully.
New secret saved to: tda_keys/jwt_secret.key
```

## Verify Installation

After running `regenerate_jwt_secret.py`, this directory should contain:

```bash
ls -la tda_keys/
# Expected files:
# - jwt_secret.key   (44 bytes, newly generated)
# - license.key      (1.2 KB, provided)
# - public_key.pem   (800 bytes, provided)
# - README.md        (this file)
```

## Security Notes

- **NEVER commit `jwt_secret.key` to version control** - It's already in `.gitignore`
- Regenerate `jwt_secret.key` for each deployment environment (dev, staging, production)
- Keep `license.key` backed up securely - it's required for startup
- `public_key.pem` is safe to distribute and required for prompt decryption

## Application Startup

The platform will **fail to start** if `jwt_secret.key` is missing. You will see:

```
ERROR: JWT secret key not found at tda_keys/jwt_secret.key
Please run: python maintenance/regenerate_jwt_secret.py
```

**Solution**: Run the regeneration script (see "First-Time Setup" above)

## Multi-Environment Deployments

For production deployments across multiple environments:

1. **Development**:
   ```bash
   python maintenance/regenerate_jwt_secret.py
   # Creates unique dev JWT secret
   ```

2. **Staging**:
   ```bash
   python maintenance/regenerate_jwt_secret.py
   # Creates unique staging JWT secret
   ```

3. **Production**:
   ```bash
   python maintenance/regenerate_jwt_secret.py
   # Creates unique production JWT secret
   ```

**Each environment MUST have its own `jwt_secret.key`** - never copy between environments.

## Troubleshooting

**Problem**: Application won't start, "JWT secret key not found"
```bash
# Solution
python maintenance/regenerate_jwt_secret.py
```

**Problem**: "License key not found" or "Invalid license"
```bash
# Verify license.key exists and is valid
ls -lh tda_keys/license.key
# Contact: info@uderia.com if license is missing or corrupted
```

**Problem**: "Failed to decrypt system prompts"
```bash
# Verify public_key.pem exists
ls -lh tda_keys/public_key.pem
# This file should be included in V1.0.0 - if missing, restore from distribution
```

## For More Information

- Installation Guide: `README.md` (repository root)
- Security Architecture: `docs/Architecture/PROMPT_ENCRYPTION.md`
- Development Guide: `CLAUDE.md`
- Support: info@uderia.com
