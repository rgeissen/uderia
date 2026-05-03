# Uderia Security Architecture

## Executive Summary

Uderia implements a **multi-layer enterprise security architecture** spanning authentication, authorization, secrets management, cryptographic data protection, audit logging, and enterprise identity federation. The platform is designed from the ground up for zero-trust deployments where data sovereignty and accountability are non-negotiable.

Five complementary security systems work together to provide end-to-end trust guarantees:

| System | What it protects |
|---|---|
| **License-Based Prompt Encryption** | Intellectual property in system prompts — at distribution, at rest, at runtime |
| **Execution Provenance Chain (EPC)** | Integrity of every LLM decision, tool call, and response |
| **Authentication & Identity Federation** | User identity via passwords, OAuth, OIDC, SAML 2.0 SSO |
| **Secrets & Credential Management** | LLM API keys, SSO secrets, connector credentials |
| **Access Control & Consumption Governance** | Who can do what, and how much |

Together these establish a **zero-trust execution model**: the intelligence that drives the AI is cryptographically protected, and every action the AI takes is cryptographically recorded. This positions Uderia for enterprise compliance requirements including SOX audit trails, GDPR accountability, EU AI Act transparency mandates, and ISO 27001 information security management.

---

## Table of Contents

1. [Key Inventory](#1-key-inventory)
2. [Authentication Systems](#2-authentication-systems)
   - [JWT Session Tokens](#21-jwt-session-tokens)
   - [Long-Lived Access Tokens](#22-long-lived-access-tokens)
   - [Password Authentication](#23-password-authentication)
   - [OAuth 2.0 Social Login](#24-oauth-20-social-login)
   - [OIDC Enterprise SSO](#25-oidc-enterprise-sso-phase-1)
   - [SAML 2.0 Enterprise SSO](#26-saml-20-enterprise-sso-phase-2)
   - [Email Verification](#27-email-verification)
3. [Authorization & Access Control](#3-authorization--access-control)
   - [User Tiers](#31-user-tiers)
   - [Decorator Enforcement](#32-decorator-enforcement)
   - [Pane Visibility Controls](#33-pane-visibility-controls)
   - [Consumption Profiles & Rate Limiting](#34-consumption-profiles--rate-limiting)
4. [Secrets & Credential Management](#4-secrets--credential-management)
   - [Per-User LLM Credential Encryption](#41-per-user-llm-credential-encryption)
   - [Platform Connector Credentials](#42-platform-connector-credentials)
   - [SSO Client Secret Encryption](#43-sso-client-secret-encryption)
   - [REDACTED Sentinel Pattern](#44-redacted-sentinel-pattern)
5. [License-Based Prompt Encryption](#5-license-based-prompt-encryption)
6. [Execution Provenance Chain (EPC)](#6-execution-provenance-chain-epc)
7. [Audit Logging](#7-audit-logging)
   - [JWT & Access Token Audit Trail](#71-jwt--access-token-audit-trail)
   - [Failed Login & Account Lockout](#72-failed-login--account-lockout)
   - [SSO Group Sync Audit Log](#73-sso-group-sync-audit-log)
   - [General Audit Log](#74-general-audit-log)
8. [Network Security](#8-network-security)
9. [Platform Connector Security](#9-platform-connector-security)
10. [Threat Model](#10-threat-model)
11. [Enterprise Compliance](#11-enterprise-compliance)
12. [Performance Impact](#12-performance-impact)

---

## 1. Key Inventory

All cryptographic keys reside in `/tda_keys/` with restricted filesystem permissions.

| File | Algorithm | Purpose | Auto-Generated | Rotation |
|---|---|---|:-:|---|
| `public_key.pem` | RSA-4096 | License signature verification + bootstrap key derivation | No (shipped) | Requires re-issuing all licenses |
| `license.key` | RSA-PSS signed JSON | License validation + per-tier database key derivation | No (issued) | New license file |
| `jwt_secret.key` | HMAC-SHA256 (256-bit) | JWT session token signing | Yes (first use) | `maintenance/regenerate_jwt_secret.py` |
| `provenance_key.pem` | Ed25519 (private PKCS8) | EPC chain step signing | Yes (first use) | `maintenance/rotate_provenance_key.py` |
| `provenance_key.pub` | Ed25519 (public) | EPC chain offline verification | Yes (generated with private) | Rotated together |

**Environment variables that override file-based keys:**

| Variable | Purpose | Default |
|---|---|---|
| `TDA_JWT_SECRET_KEY` | Override `jwt_secret.key` | File-based key |
| `TDA_ENCRYPTION_KEY` | Master key for per-user credential encryption | Dev default (change in production!) |
| `TDA_JWT_EXPIRY_HOURS` | JWT token lifetime | `24` |
| `TDA_MAX_LOGIN_ATTEMPTS` | Failed login lockout threshold | `5` |
| `TDA_LOCKOUT_DURATION_MINUTES` | Account lock duration | `15` |
| `TDA_PROGRESSIVE_DELAY_BASE_SECONDS` | Progressive delay base per failed attempt | `2` |
| `TDA_PROGRESSIVE_DELAY_MAX_SECONDS` | Cap on progressive delay | `30` |
| `TDA_PASSWORD_MIN_LENGTH` | Minimum password length | `8` |

---

## 2. Authentication Systems

### 2.1 JWT Session Tokens

JWT tokens authenticate browser sessions via the `Authorization: Bearer <token>` header.

**Cryptographic algorithm:** HS256 (HMAC-SHA256)

**Token structure:**
```json
{
  "user_id": "uuid",
  "username": "string",
  "exp": "unix timestamp",
  "iat": "unix timestamp",
  "jti": "secrets.token_urlsafe(32)"
}
```

**Lifecycle and storage:**
- Default expiry: 24 hours (`TDA_JWT_EXPIRY_HOURS`)
- Token hash (SHA-256) stored in `auth_tokens` table for revocation tracking
- In-memory LRU cache (10,000 entries, 60-second TTL) eliminates 2 DB queries per request at steady state
- Per-token revocation via `AuthToken.revoked` flag; cache invalidated on revoke
- IP address and user agent recorded at issuance

**Internal service tokens:** Used by the Genie coordinator for child session creation. 30-minute expiry, marked `"internal": True` in payload, not stored in the database.

**Files:** `src/trusted_data_agent/auth/security.py`, `src/trusted_data_agent/auth/middleware.py`

---

### 2.2 Long-Lived Access Tokens

API access tokens authenticate programmatic REST API clients without session management overhead.

**Format:** `tda_` prefix + `secrets.token_urlsafe(24)` (~40 characters total)

**Storage model:**
- Full token displayed **once** at creation — never stored in plaintext
- SHA-256 hash stored in `access_tokens` table
- First 12 characters (`token_prefix`) kept for UI display ("tda_abc12...")

**`access_tokens` table schema:**
```sql
id            UUID PRIMARY KEY
user_id       TEXT REFERENCES users(id)
token_prefix  VARCHAR(10) INDEXED        -- for display only
token_hash    VARCHAR(255) UNIQUE        -- SHA-256 of full token
name          VARCHAR(100)               -- human-readable label
created_at    DATETIME
expires_at    DATETIME (NULL = never)
last_used_at  DATETIME                   -- updated on each successful auth
use_count     INTEGER DEFAULT 0          -- incremented per auth
last_ip_address VARCHAR(45)              -- IPv6-compatible, last request IP
revoked       BOOLEAN DEFAULT FALSE
revoked_at    DATETIME
```

**Files:** `src/trusted_data_agent/auth/security.py`

---

### 2.3 Password Authentication

**Hashing:** bcrypt with 12 rounds (work factor). Per-password random salt auto-generated by bcrypt.

**Verification:** Constant-time comparison via bcrypt's built-in `checkpw()`.

**Strength requirements** (validated at registration and password change):
- Minimum length: `TDA_PASSWORD_MIN_LENGTH` (default 8)
- At least one uppercase letter
- At least one lowercase letter
- At least one digit

**Password reset token:**
```sql
id         UUID PRIMARY KEY
user_id    TEXT REFERENCES users(id)
token_hash VARCHAR(255) UNIQUE INDEX  -- SHA-256 of reset token
expires_at DATETIME (1 hour from creation)
created_at DATETIME
used       BOOLEAN DEFAULT FALSE
used_at    DATETIME
```

Reset tokens are single-use; `is_valid()` checks `used IS FALSE AND expires_at > now()`.

**Failed login and lockout:** See [Section 7.2](#72-failed-login--account-lockout).

**Files:** `src/trusted_data_agent/auth/security.py`

---

### 2.4 OAuth 2.0 Social Login

Supported providers: **Google, GitHub, Microsoft, Discord, Okta** (extensible via `oauth_handlers.py`).

**Flow:** Standard OAuth 2.0 Authorization Code. Access token exchanged for provider user info. JIT (Just-In-Time) user provisioning on first login.

**`oauth_accounts` table:**
```sql
id                  UUID PRIMARY KEY
user_id             TEXT REFERENCES users(id)
provider            VARCHAR(50)         -- 'google', 'github', etc.
provider_user_id    VARCHAR(255)        -- provider's unique ID
provider_email      VARCHAR(255)
provider_name       VARCHAR(255)
provider_picture_url TEXT
provider_metadata   JSON                -- additional profile data
created_at          DATETIME
updated_at          DATETIME
last_used_at        DATETIME
UNIQUE(provider, provider_user_id)
```

**Security properties:**
- No OAuth tokens stored beyond the authorization code exchange
- Email verification optional per provider
- Duplicate email detection across authentication methods

**Files:** `src/trusted_data_agent/auth/oauth_handlers.py`, `src/trusted_data_agent/api/auth_routes.py`

---

### 2.5 OIDC Enterprise SSO (Phase 1)

Generic OIDC federation via `/.well-known/openid-configuration` discovery. Supports any standards-compliant IdP (Okta, Azure AD, Auth0, Keycloak, Google Workspace, etc.).

**`sso_configurations` table:**
```sql
id               UUID PRIMARY KEY
name             TEXT NOT NULL
provider         TEXT DEFAULT 'oidc'
issuer_url       TEXT NOT NULL          -- used for discovery doc fetch
client_id        TEXT NOT NULL
client_secret    TEXT                   -- Fernet-encrypted
discovery_doc    TEXT                   -- cached JSON, TTL 3600s
discovery_cached_at DATETIME
scopes           TEXT DEFAULT '["openid","profile","email"]'
email_claim      TEXT DEFAULT 'email'
name_claim       TEXT DEFAULT 'name'
groups_claim     TEXT                   -- e.g. 'groups'
sub_claim        TEXT DEFAULT 'sub'
group_tier_map   TEXT                   -- JSON: {"GroupName": "admin"}
default_tier     TEXT DEFAULT 'user'
enabled          INTEGER DEFAULT 1
auto_provision_users INTEGER DEFAULT 1
require_email_verification INTEGER DEFAULT 0
button_label     TEXT
icon_url         TEXT
created_at       DATETIME
updated_at       DATETIME
```

**`sso_sessions` table** (for back-channel logout):
```sql
id              UUID PRIMARY KEY
user_uuid       TEXT REFERENCES users(id)
sso_config_id   TEXT REFERENCES sso_configurations(id)
id_token_hash   TEXT  -- SHA-256 of id_token for revocation lookup
sid             TEXT  -- IdP session ID (from token claims)
sub             TEXT  -- IdP subject
issued_at       DATETIME
expires_at      DATETIME
revoked         BOOLEAN DEFAULT FALSE
revoked_at      DATETIME
```

**Validation pipeline:**
1. Fetch and cache discovery document (TTL: 3600 seconds)
2. Exchange authorization code for `id_token` and `access_token` (using Fernet-decrypted `client_secret`)
3. Validate `id_token` via `python-jose`: signature, `iss`, `aud`, `exp`, nonce
4. Extract claims: email, name, groups
5. Apply group-to-tier mapping (highest-privilege group wins)
6. JIT-provision user or update existing user's tier

**Back-channel logout:** IdP posts logout token → `id_token_hash` lookup → session revoked

**API responses:** `client_secret` always returned as `"[REDACTED]"` — the literal secret never leaves the server.

**Files:** `src/trusted_data_agent/auth/oidc_provider.py`, `src/trusted_data_agent/api/auth_routes.py`

---

### 2.6 SAML 2.0 Enterprise SSO (Phase 2)

Full SAML 2.0 Service Provider implementation supporting enterprise IdPs (Active Directory FS, Okta, Azure AD, OneLogin, PingIdentity).

#### Service Provider Role

Uderia acts as the SP. It:
- Generates signed `AuthnRequest` via HTTP-Redirect binding (raw deflate + base64 + URL encoding)
- Exposes SP metadata XML at `GET /api/v1/auth/saml/<id>/metadata` (paste into IdP configuration)
- Receives signed `SAMLResponse` via HTTP-POST binding at the Assertion Consumer Service (ACS)

**`saml_configurations` table:**
```sql
id                TEXT PRIMARY KEY
name              TEXT NOT NULL
sp_entity_id      TEXT NOT NULL       -- SP's unique identifier
sp_acs_url        TEXT                -- computed from base URL if null
sp_private_key    TEXT                -- PEM, Fernet-encrypted
sp_certificate    TEXT                -- PEM public cert
idp_entity_id     TEXT NOT NULL       -- IdP's unique identifier
idp_sso_url       TEXT NOT NULL       -- IdP login endpoint
idp_slo_url       TEXT                -- IdP logout endpoint (optional)
idp_certificate   TEXT NOT NULL       -- PEM cert for assertion signature verification
email_attr        TEXT DEFAULT 'email'
name_attr         TEXT DEFAULT 'displayName'
groups_attr       TEXT                -- attribute name carrying group list
default_tier      TEXT DEFAULT 'user'
group_tier_map    TEXT                -- JSON: {"GroupName": "tier"}
auto_provision_users INTEGER DEFAULT 1
enabled           INTEGER DEFAULT 1
button_label      TEXT
icon_url          TEXT
display_order     INTEGER DEFAULT 0
created_at        DATETIME
updated_at        DATETIME
```

#### AuthnRequest Generation

```
1. Build SAML 2.0 AuthnRequest XML
2. UTF-8 encode
3. Deflate with raw DEFLATE (zlib, stripping 2-byte header and 4-byte checksum)
4. Base64 encode
5. URL encode
6. Append as SAMLRequest= query parameter to idp_sso_url
7. Add RelayState= (random UUID, stored in in-memory map for relay-to-destination)
```

#### Assertion Validation Pipeline

On ACS POST (`POST /api/v1/auth/saml/<id>/acs`):

1. **Decode** SAMLResponse from base64
2. **Parse** XML with `lxml.etree`
3. **Verify XML digital signature** using `signxml.XMLVerifier` and the configured IdP certificate (PEM)
   - Rejects any assertion not signed by the expected IdP
   - Signature covers the Assertion element
4. **Validate assertion fields:**
   - `Issuer` matches `idp_entity_id`
   - `Recipient` matches ACS URL
   - `NotOnOrAfter` has not passed (clock tolerance: none — use IdP NTP sync)
   - `NotBefore` is in the past
5. **Extract attributes:** email, name, groups from the configured attribute names
6. **Resolve effective tier:** highest-privilege group mapping wins (see below)
7. **JIT-provision** user or sync existing user's tier/groups
8. **Issue JWT** and redirect to `/?token=<jwt>&method=saml`

On validation failure, user is redirected to `/login?error=<reason>` — no sensitive details exposed.

#### Group-to-Tier Resolution

Groups are extracted from the SAML assertion. The effective tier is the highest-privilege tier across all groups the user belongs to:

```python
_tier_order = {'user': 0, 'developer': 1, 'admin': 2}
tier = cfg['default_tier']  # starting point
for group in user_groups:
    mapped = group_tier_map.get(group)
    if mapped and _tier_order[mapped] > _tier_order[tier]:
        tier = mapped
# Result: highest privilege wins
```

This is **always re-evaluated on every login** — tier changes in the IdP take effect on the user's next authentication, with no manual intervention required.

#### SP Private Key Security

The SP's private key (used to sign AuthnRequests to IdPs that require signed requests) is stored Fernet-encrypted in the database. The API never returns the raw key — responses show `"[REDACTED]"` to confirm the key is configured without exposing its value.

**Files:** `src/trusted_data_agent/auth/saml_provider.py`, `src/trusted_data_agent/api/auth_routes.py`

---

### 2.7 Email Verification

**`email_verification_tokens` table:**
```sql
id                UUID PRIMARY KEY
user_id           TEXT REFERENCES users(id)
token_hash        VARCHAR(255) UNIQUE INDEX  -- SHA-256 of verification token
email             VARCHAR(255) INDEXED
verification_type TEXT  -- 'oauth', 'signup', 'email_change'
oauth_provider    TEXT  -- 'google' etc. when type='oauth'
expires_at        DATETIME (24 hours from creation)
verified_at       DATETIME (NULL until verified)
created_at        DATETIME
```

Tokens are single-use and time-limited. `is_valid()` checks both `verified_at IS NULL` and `expires_at > now()`.

---

## 3. Authorization & Access Control

### 3.1 User Tiers

Three-tier hierarchy stored as `User.profile_tier (VARCHAR(20))` and `User.is_admin (BOOLEAN)`:

| Tier | `profile_tier` | `is_admin` | Capabilities |
|---|---|:-:|---|
| **User** | `'user'` | false | Execute queries, manage own profiles and collections, view own sessions |
| **Developer** | `'developer'` | false | All User capabilities + create/modify profiles, configure data sources, access REST API |
| **Admin** | `'admin'` | true | All Developer capabilities + user management, system configuration, platform connector governance, security settings, compliance reporting |

Tier is re-evaluated on every SSO login. Manual tier changes by admins take effect immediately.

---

### 3.2 Decorator Enforcement

All route protection is enforced by middleware decorators in `src/trusted_data_agent/auth/middleware.py`:

**`@require_auth`:**
- Extracts `Authorization: Bearer <token>` header
- Tries access token format (`tda_` prefix) first, then JWT
- Injects `current_user: User` as first positional argument
- Returns `401 Unauthorized` if unauthenticated

**`@require_admin`:**
- Full authentication (same as `@require_auth`)
- Additionally checks `current_user.is_admin == True`
- Returns `403 Forbidden` if authenticated but not admin
- **Note:** Do not stack `@require_auth` on top of `@require_admin` — both inject `current_user`, causing double injection. Use only `@require_admin` for admin routes.

**`@optional_auth`:**
- Attempts authentication; passes `current_user=None` if unauthenticated
- Used for public endpoints that behave differently when authenticated

---

### 3.3 Pane Visibility Controls

UI panel visibility is governed per tier by the `pane_visibility` table:

```sql
id               UUID PRIMARY KEY
pane_id          VARCHAR(50) UNIQUE  -- 'conversation', 'executions', 'rag-maintenance',
                                    --  'marketplace', 'credentials', 'admin'
pane_name        VARCHAR(100)
visible_to_user      BOOLEAN
visible_to_developer BOOLEAN
visible_to_admin     BOOLEAN
description      VARCHAR(255)
display_order    INTEGER
created_at, updated_at DATETIME
```

This allows admins to customize which panels are visible to each tier, e.g., hiding the `admin` panel from non-admin users.

---

### 3.4 Consumption Profiles & Rate Limiting

#### Consumption Profiles (Per-User Token Quotas)

Consumption profiles govern per-user resource limits and are assigned to users by admins.

**`consumption_profiles` table:**
```sql
id                     INTEGER PRIMARY KEY
name                   VARCHAR(100) UNIQUE INDEX
description            TEXT
prompts_per_hour       INTEGER DEFAULT 100
prompts_per_day        INTEGER DEFAULT 1000
config_changes_per_hour INTEGER DEFAULT 10
input_tokens_per_month  INTEGER (NULL = unlimited)
output_tokens_per_month INTEGER (NULL = unlimited)
is_default             BOOLEAN INDEXED
is_active              BOOLEAN
created_at, updated_at DATETIME
```

**Enforcement fail-closed:** If the enforcer throws an exception (e.g., DB unavailable), the request is **blocked** (not silently bypassed). Bypass attempts increment an audit counter.

#### IP-Based Rate Limiting

Token-bucket algorithm protecting authentication endpoints:

| Endpoint class | Default limit |
|---|---|
| Login | 5 per minute per IP |
| Registration | 3 per hour per IP |
| API | 60 per minute per IP |
| User prompts | 100 per hour per user |

IP extraction priority: `X-Forwarded-For` → `X-Real-IP` → `remote_addr`

Rate limits are configurable by admins at `Administration → App Config → Security & Rate Limiting`.

**Files:** `src/trusted_data_agent/auth/consumption_enforcer.py`, `src/trusted_data_agent/auth/rate_limiter.py`

---

## 4. Secrets & Credential Management

### 4.1 Per-User LLM Credential Encryption

LLM provider API keys are encrypted per user using keys derived from a platform master key.

**Key derivation (PBKDF2-HMAC-SHA256):**
```python
kdf = PBKDF2HMAC(
    algorithm=SHA256(),
    length=32,           # 256-bit Fernet key
    salt=user_id.encode(),   # Per-user salt (user UUID as bytes)
    iterations=100_000,  # NIST-recommended iteration count
)
key = base64.urlsafe_b64encode(kdf.derive(MASTER_ENCRYPTION_KEY.encode()))
```

**Encryption:** Fernet (AES-128-CBC + HMAC-SHA256 with timestamp). The Fernet timestamp allows detecting token age but does not enforce expiry.

**Master key:** `TDA_ENCRYPTION_KEY` environment variable. Change this immediately on production installation. Key rotation utility: `rotate_encryption_key(old_key, new_key)` — decrypts all credentials with old key and re-encrypts with new.

**`user_credentials` table:**
```sql
id                   UUID PRIMARY KEY
user_id              TEXT REFERENCES users(id)
provider             VARCHAR(50)   -- 'Amazon', 'Google', 'OpenAI', etc.
credentials_encrypted TEXT          -- Fernet ciphertext
created_at, updated_at DATETIME
UNIQUE(user_id, provider)
```

**Files:** `src/trusted_data_agent/auth/encryption.py`

---

### 4.2 Platform Connector Credentials

Admin-configured credentials for platform connectors (browser, web search, Google Workspace, etc.) use a shared Fernet key derived from the same master key but with a **frozen salt**.

```python
salt = b'platform_mcp_registry'  # INTENTIONALLY FROZEN
kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=100_000)
key = base64.urlsafe_b64encode(kdf.derive(TDA_ENCRYPTION_KEY.encode()))
return Fernet(key)
```

**Critical:** The salt `b'platform_mcp_registry'` is intentionally frozen even though the module was renamed. Changing it would make all existing admin credentials permanently unreadable. Do not change the salt.

**Files:** `src/trusted_data_agent/core/platform_connector_registry.py`

---

### 4.3 SSO Client Secret Encryption

Both OIDC `client_secret` and SAML `sp_private_key` are encrypted with the same `_platform_fernet()` function (frozen-salt Fernet) before storage.

Encryption happens at create/update time in `oidc_provider.py` and `saml_provider.py`. The Fernet-encrypted ciphertext is stored in the database.

---

### 4.4 REDACTED Sentinel Pattern

All API responses that would expose a sensitive field instead return the string literal `"[REDACTED]"`. This communicates to the client that the credential is configured without revealing its value.

**Fields using this pattern:**

| Resource | Field | Route |
|---|---|---|
| OIDC configuration | `client_secret` | `GET /api/v1/auth/sso/configurations`, `GET /api/v1/auth/sso/configurations/<id>` |
| SAML configuration | `sp_private_key` | `GET /api/v1/auth/saml/configurations`, `GET /api/v1/auth/saml/configurations/<id>` |
| Access tokens | Full token value | `POST /api/v1/auth/access-tokens` (one-time display) |

**Update guard:** When a PUT request sends `"[REDACTED]"` for one of these fields, the server skips re-encryption — the existing encrypted value in the database is preserved unchanged. Only a new, non-`"[REDACTED]"` value triggers encryption and storage update.

---

## 5. License-Based Prompt Encryption

System prompts encode strategic planning logic, tactical tool selection, error recovery strategies, and domain-specific reasoning patterns. They are protected through a **two-layer encryption model** tied to each customer's license.

### 5.1 Cryptographic Primitives

| Layer | Algorithm | Key Derivation | Salt | Iterations |
|---|---|---|---|---|
| **License Signing** | RSA-PSS (4096-bit, SHA-256, MGF1) | N/A | N/A | N/A |
| **Bootstrap Encryption** | Fernet (AES-128-CBC + HMAC-SHA256) | PBKDF2-HMAC-SHA256 | `b'uderia_bootstrap_prompts_v1'` | 100,000 |
| **Tier Encryption** | Fernet (AES-128-CBC + HMAC-SHA256) | PBKDF2-HMAC-SHA256 | `b'uderia_tier_prompts_v1'` | 100,000 |

### 5.2 Three-Phase Lifecycle

```
DEVELOPMENT            DISTRIBUTION              RUNTIME
plain text prompts  →  default_prompts.dat  →  tda_auth.db prompts table
(license repo)         (RSA-4096 key)           (license + tier key)
```

**Phase 1 — Development:** Plain-text `.txt` prompt files are encrypted with a key derived from the RSA-4096 public key using `encrypt_default_prompts.py`. The result is `schema/default_prompts.dat` (committed to the repository).

**Phase 2 — Bootstrap (first startup):** `default_prompts.dat` is decrypted using the RSA-4096 key. Each prompt is re-encrypted with a key derived from the customer's license signature + their tier, then stored in the `prompts` table of `tda_auth.db`. This binds database content to the specific license — different customers produce different ciphertext even for identical prompts.

**Phase 3 — Runtime:** `PromptLoader` decrypts prompts on demand using the license-derived tier key. Results are cached in memory; the database is not re-queried on every LLM call.

### 5.3 License Structure

```json
{
  "payload": {
    "holder": "customer@company.com",
    "issued_at": "ISO 8601 timestamp",
    "expires_at": "ISO 8601 timestamp",
    "tier": "Standard | Prompt Engineer | Enterprise"
  },
  "signature": "hex-encoded RSA-PSS signature of payload"
}
```

Verification at startup: signature validated with `public_key.pem`, expiry checked. The application refuses to start if the license is invalid or expired.

### 5.4 Tier-Based Access Control

| Capability | Standard | Prompt Engineer | Enterprise |
|---|:-:|:-:|:-:|
| Runtime LLM decryption | Yes | Yes | Yes |
| View/edit in System Prompts UI | — | Yes | Yes |
| Profile-level prompt overrides | — | Yes | Yes |
| User-level prompt overrides | — | — | Yes |

### 5.5 Protected Prompts (15 total)

`MASTER_SYSTEM_PROMPT`, `GOOGLE_MASTER_SYSTEM_PROMPT`, `OLLAMA_MASTER_SYSTEM_PROMPT`, `WORKFLOW_META_PLANNING_PROMPT`, `WORKFLOW_TACTICAL_PROMPT`, `TASK_CLASSIFICATION_PROMPT`, `ERROR_RECOVERY_PROMPT`, `TACTICAL_SELF_CORRECTION_PROMPT` (column/table variants), `SQL_CONSOLIDATION_PROMPT`, `CONVERSATION_EXECUTION`, `CONVERSATION_WITH_TOOLS_EXECUTION`, `GENIE_COORDINATOR_PROMPT`, `RAG_FOCUSED_EXECUTION`

### 5.6 Key Properties

- **License-specific keys** — different customers cannot decrypt each other's database
- **RSA-PSS 4096-bit** — prevents license forgery
- **Fernet authenticated encryption** — AES-128-CBC + HMAC-SHA256, provides both confidentiality and integrity; corruption is detectable
- **Zero-downtime deployment** — `update_prompt.py` updates running installations with automatic cache invalidation via `POST /v1/admin/prompts/clear-cache`

**Files:** `src/trusted_data_agent/agent/prompt_encryption.py`, `src/trusted_data_agent/agent/prompt_loader.py`

---

## 6. Execution Provenance Chain (EPC)

The EPC creates an immutable, cryptographically signed audit trail covering every LLM decision, tool call, and response. It enables offline verification that no step was injected, modified, or replayed.

### 6.1 Cryptographic Primitives

| Operation | Algorithm | Output Size |
|---|---|---|
| Content hashing | SHA-256 | 64 hex characters |
| Chain linking | SHA-256 of `{index}:{type}:{content_hash}:{prev_hash}` | 64 hex characters |
| Step signing | Ed25519 | 64-byte signature (base64) |
| Key fingerprint | SHA-256 of Ed25519 public key raw bytes | 64 hex characters |

### 6.2 Chain Structure

Each execution step becomes a provenance record:

```json
{
  "step_id": "uuid",
  "step_index": 0,
  "step_type": "query_intake | strategic_plan | tool_call | tool_result | ...",
  "timestamp": "ISO 8601",
  "content_hash": "sha256(content[:4096])",
  "previous_hash": "chain_hash of prior step (or GENESIS_HASH for turn 1 step 0)",
  "chain_hash": "sha256('{index}:{type}:{content_hash}:{previous_hash}')",
  "signature": "base64(Ed25519.sign(chain_hash))",
  "content_summary": "≤200 characters human-readable"
}
```

Content is hashed but never stored — sensitive data (queries, responses, tool outputs) does not appear in provenance records.

**Genesis hash:** `"0000...0000"` (64 zeros) for the first step of the first turn in a session.

### 6.3 Cross-Turn Chain Linking

The first step of each subsequent turn includes `"previous_turn_tip_hash"` pointing to the final step hash of the prior turn. This creates a hash chain spanning the entire session:

```
Turn 1: [query_intake] → [strategic_plan] → [tool_call] → [complete]
                                                                ↓ tip
Turn 2: [query_intake] → [llm_call] → [response] → [complete]
           ↑ previous_turn_tip = Turn 1 tip
```

### 6.4 Cross-Session Linking (Genie Coordinator)

When the Genie coordinator spawns child sessions, each child session's chain tip is recorded as a `child_chain_ref` step in the parent's provenance chain. This creates a Merkle-tree-like structure linking the entire multi-session execution into a single verifiable unit.

### 6.5 Step Coverage (22 Step Types)

| Profile Class | Steps Recorded |
|---|---|
| **Optimize** (`tool_enabled`) | `query_intake`, `rag_retrieval`, `strategic_plan`, `plan_rewrite`, `tactical_decision`, `tool_call`, `tool_result`, `self_correction`, `synthesis`, `complete` |
| **Ideate** (`llm_only`) | `query_intake`, `knowledge_retrieval`, `llm_call`, `llm_response`, `complete` |
| **Focus** (`rag_focused`) | `query_intake`, `rag_search`, `rag_results`, `synthesis`, `complete` |
| **Ideate + MCP** (`conversation_with_tools`) | `query_intake`, `agent_tool_call`, `agent_tool_result`, `agent_llm_step`, `complete` |
| **Coordinate** (`genie`) | `query_intake`, `child_dispatch`, `child_chain_ref`, `coordinator_synthesis`, `complete` |

### 6.6 Provenance Metadata (Per Turn)

```json
{
  "chain_version": 1,
  "key_fingerprint": "sha256hex of Ed25519 public key",
  "profile_type": "tool_enabled | genie | ...",
  "session_id": "uuid",
  "turn_number": 1,
  "user_uuid": "uuid",
  "step_count": 8,
  "chain_root_hash": "hash of first step",
  "chain_tip_hash": "hash of last step",
  "previous_turn_tip_hash": "cross-turn link",
  "sealed": true
}
```

### 6.7 Three Verification Levels

1. **Chain Integrity** (offline-capable) — verifies hash linking, SHA-256 computations, and Ed25519 signatures using only the public key. No access to session data required.

2. **Content Verification** — recomputes content hashes from actual session data files and confirms they match provenance records. Detects content tampering after the fact.

3. **Session Integrity** — verifies all turns link correctly via `previous_turn_tip_hash` and Genie's cross-session `child_chain_ref` references. Detects turn injection or removal.

### 6.8 REST API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/sessions/{id}/provenance` | Full provenance for all turns |
| `GET` | `/api/v1/sessions/{id}/provenance/turn/{n}` | Single turn provenance |
| `POST` | `/api/v1/sessions/{id}/provenance/verify` | Verify chain integrity (returns pass/fail + details) |
| `GET` | `/api/v1/sessions/{id}/provenance/export` | Download full JSON for offline audit |
| `GET` | `/api/v1/provenance/public-key` | Download Ed25519 public key PEM for independent verification |

### 6.9 Key Properties

- **Zero new dependencies** — uses the `cryptography` library already present in the project
- **Negligible overhead** — ~100 microseconds per step (hash + sign), invisible against LLM latency
- **Degraded mode** — if the signing key is unavailable, hashes are still recorded (unsigned); execution continues unblocked
- **Key rotation** — `maintenance/rotate_provenance_key.py` generates new keys; existing chains remain verifiable via stored `key_fingerprint`
- **Backward compatible** — sessions without provenance data handled gracefully

---

## 7. Audit Logging

### 7.1 JWT & Access Token Audit Trail

**JWT tokens** (`auth_tokens` table):
```sql
id           UUID PRIMARY KEY
user_id      TEXT REFERENCES users(id)
token_hash   VARCHAR(255) UNIQUE  -- SHA-256 of token
expires_at   DATETIME
created_at   DATETIME
ip_address   VARCHAR(45)          -- IPv6-compatible
user_agent   VARCHAR(500)
revoked      BOOLEAN DEFAULT FALSE
revoked_at   DATETIME
INDEX(user_id, revoked, expires_at)
```

**Access tokens** — per-use audit fields on `access_tokens` table: `last_used_at`, `use_count`, `last_ip_address` (updated on every successful authentication).

---

### 7.2 Failed Login & Account Lockout

Fields on the `users` table:
```sql
failed_login_attempts  INTEGER DEFAULT 0
locked_until           DATETIME (NULL if not locked)
last_failed_login_at   DATETIME
```

**Lockout thresholds** (configurable via environment variables):
- After `TDA_MAX_LOGIN_ATTEMPTS` (default: 5) consecutive failures → account locked for `TDA_LOCKOUT_DURATION_MINUTES` (default: 15 minutes)
- Progressive delay between attempts: `min(base * 2^(attempts-2), max_seconds)`
  - 1st failure: no delay; 2nd: 2s; 3rd: 4s; 4th: 8s; 5th: 16s → lockout

On successful login: `failed_login_attempts` reset to 0, `locked_until` cleared.

---

### 7.3 SSO Group Sync Audit Log

Every change to a user's tier or group membership via SSO is recorded — whether on login (automatic re-sync) or via manual admin action.

**`sso_sync_events` table:**
```sql
id           UUID PRIMARY KEY
user_uuid    TEXT REFERENCES users(id)
config_id    TEXT  -- SSO provider config ID (NULL for manual syncs)
config_type  TEXT  -- 'oidc' | 'saml'
sync_type    TEXT  -- 'login' | 'manual'
old_tier     TEXT  -- tier before this sync
new_tier     TEXT  -- tier after this sync
old_groups   TEXT  -- JSON array of groups before
new_groups   TEXT  -- JSON array of groups after
changed      INTEGER DEFAULT 0  -- 1 if tier or groups actually changed
synced_at    DATETIME DEFAULT (datetime('now'))
```

This table supports:
- Compliance reporting: who had what tier, when, and why
- Incident investigation: which IdP group change triggered a privilege change
- Access reviews: complete timeline of every user's group and tier changes

Admin endpoint: `GET /api/v1/auth/sso/users/<id>/sync-history`

---

### 7.4 General Audit Log

**`audit_logs` table:**
```sql
id          UUID PRIMARY KEY
user_id     TEXT (nullable — pre-auth events)
action      VARCHAR(50)  -- 'login', 'logout', 'configure', 'execute', etc.
resource    VARCHAR(255) -- endpoint or resource path
status      VARCHAR(20)  -- 'success' | 'failure'
ip_address  VARCHAR(45)
user_agent  VARCHAR(500)
details     TEXT         -- JSON for extensibility
timestamp   DATETIME
INDEX(user_id, timestamp)
INDEX(action, timestamp)
```

---

## 8. Network Security

### 8.1 TLS/HTTPS

The platform is designed to run behind a reverse proxy (nginx, Caddy, Traefik) that handles TLS termination. Direct TLS is not built into the application server.

**Production deployment requirements:**
- TLS 1.2 minimum, TLS 1.3 recommended
- HTTPS-only in production (redirect HTTP → HTTPS at proxy level)
- HSTS recommended for the proxy configuration

### 8.2 IP Address Handling

The application trusts proxy-set headers for client IP extraction (important for rate limiting accuracy):

1. `X-Forwarded-For` header — first IP in the chain (closest to client)
2. `X-Real-IP` header — direct proxy IP
3. `request.remote_addr` — direct connection fallback

**Important:** In production, restrict which IPs can set `X-Forwarded-For` to prevent IP spoofing by configuring your reverse proxy to overwrite this header.

### 8.3 Rate Limiting

IP-based token-bucket rate limiting on all authentication endpoints. See [Section 3.4](#34-consumption-profiles--rate-limiting) for limits and configuration.

---

## 9. Platform Connector Security

Platform connectors provide the AI agent with autonomous execution capabilities (browser, file system, web search, shell execution). Because these are high-privilege capabilities, they are governed by a strict three-layer architecture.

### 9.1 Namespace Separation

Platform connectors are **permanently separate** from user-configured MCP data source servers. They:
- Live in a different database table (`platform_connectors`)
- Are configured by admins, not users
- Are displayed in a separate UI panel (Platform Components → Connectors, not Configuration → MCP Servers)
- Never appear in the user-facing MCP server configuration panel

### 9.2 Three-Layer Governance Model

```
Admin Layer    →  installs connectors, sets available_tools, opt-in policy, credentials
     ↓
User Layer     →  toggles connectors on/off per profile (within admin bounds)
     ↓
Profile Layer  →  selects active tools per connector (within admin-permitted set)
```

**Admin governance fields on `platform_connectors`:**
```sql
enabled                  -- admin master switch
available_tools          -- JSON array: which tools are permitted
auto_opt_in              -- 1 = active on all profiles by default
user_can_opt_out         -- 1 = user can disable on their profile
user_can_configure_tools -- 1 = user can select individual tools
credentials              -- Fernet-encrypted admin API keys
```

### 9.3 Connector Type System

| Type | Transport | Use Case |
|---|---|---|
| `mcp_stdio` | Subprocess stdin/stdout (MCP wire protocol) | All current connectors |
| `mcp_http` | HTTP/SSE MCP endpoint | Remote/cloud-hosted connectors |
| `rest` | Direct REST API | Non-MCP tools |
| `oauth_only` | Authentication only | Google Workspace OAuth |

### 9.4 Shell Connector Security (`uderia-shell`)

The shell execution connector requires **two mandatory, independent security layers**:

**Layer 1 — Admin governance:** Controls who can access shell tools (via connector governance settings). Only explicitly enabled profiles can invoke shell tools.

**Layer 2 — Docker isolation:** Each shell tool invocation runs in a **fresh, throwaway Docker container**:
- No host filesystem access (only explicitly admin-configured mount paths)
- No outbound network by default (admin can allowlist specific domains)
- Resource limits: 1 CPU, 512MB RAM, 30-second execution timeout, 100MB disk
- Runs as non-root user inside container
- Container destroyed immediately after invocation completes

**Enable flow:** Admin must acknowledge a security disclaimer before the enable toggle appears:
> *"uderia-shell executes commands on the Uderia server inside an isolated Docker container. Docker must be installed on the host. All executions are audit-logged. By enabling this server you accept responsibility for access governance."*

**Shell execution audit log:**
```sql
CREATE TABLE shell_audit_log (
    id TEXT PRIMARY KEY,
    user_uuid TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,        -- exec_command | run_script | etc.
    command TEXT NOT NULL,          -- full command or script content
    exit_code INTEGER,
    started_at TEXT,
    completed_at TEXT,
    truncated_output TEXT           -- first 2KB of output
);
```

**Files:** `src/trusted_data_agent/core/platform_connector_registry.py`, `src/trusted_data_agent/connectors/registry.py`

---

## 10. Threat Model

| Threat | Mitigation |
|---|---|
| **Unauthorized prompt viewing** | License-based tier encryption — different keys per customer and tier |
| **Prompt tampering in database** | Fernet HMAC-SHA256 detects any modification |
| **License forgery** | RSA-PSS 4096-bit signature cannot be forged without private key |
| **Execution log tampering** | Ed25519 hash chain — any modification breaks chain verification |
| **Step injection** | Chain linking (`previous_hash`) detects inserted steps |
| **Step removal** | Step count + chain gap detects removed steps |
| **Replay attack** | Timestamps + chain context prevent reuse of old provenance steps |
| **Cross-session tampering (Genie)** | Child chain references link sessions into a Merkle tree |
| **Brute-force login** | 5 failures → 15-minute lockout + exponential progressive delay |
| **Token compromise** | Per-token revocation in database; cache TTL 60s limits blast radius |
| **Credential leakage via API** | `[REDACTED]` sentinel — secrets never returned in API responses |
| **LLM API key theft** | Per-user Fernet encryption; keys never in memory longer than needed |
| **SSO client secret theft** | Fernet-encrypted storage; `[REDACTED]` in all API responses |
| **SAML assertion forgery** | `signxml` verifies IdP certificate signature on every assertion |
| **SAML replay attack** | `NotOnOrAfter` expiry check; relay state consumed once |
| **Privilege escalation via SSO** | Group-to-tier re-evaluated on every login; all changes audit-logged |
| **Rate limit bypass** | Token bucket enforced server-side, keyed by IP with trusted proxy headers |
| **Shell code execution** | Two-layer isolation: admin governance + Docker container per invocation |
| **Man-in-the-middle (LLM calls)** | Content hashes detect response substitution in provenance chain |
| **Master key compromise** | Key rotation utility; credentials re-encrypted without downtime |
| **Prompt key compromise** | Re-issue license; all tiers re-derive keys on next startup |

---

## 11. Enterprise Compliance

| Regulation | Requirement | How Uderia Addresses It |
|---|---|---|
| **EU AI Act** | Transparency and traceability for AI systems | EPC records every LLM call, tool selection, and response with Ed25519-signed cryptographic proof |
| **GDPR Art. 22** | Right to explanation of automated decisions | Provenance chain traces each decision from query to final answer |
| **GDPR Art. 30** | Records of processing activities | Session-level provenance with cross-turn integrity; SSO sync event log |
| **SOX** | Audit trails for financial reporting | Tamper-evident record of every AI-assisted operation, offline-verifiable |
| **ISO 27001** | Information security management | Encrypted prompts, signed execution logs, key management procedures, access controls |
| **HIPAA** | Audit controls for access to ePHI | JWT/access token audit trail; session isolation; consumption enforcement |
| **FedRAMP (guidance)** | Cryptographic key management | Documented key rotation procedures; Ed25519 for signing; RSA-4096 for licenses |

---

## 12. Performance Impact

| Operation | Latency | When |
|---|---|---|
| Prompt decryption | <10ms | First load; cached in memory thereafter |
| Bootstrap re-encryption | 2–3 seconds | One-time on first startup |
| Provenance step (hash + sign) | ~100 microseconds | Per execution step |
| Chain verification Level 1 | ~1ms | On-demand via REST API |
| License verification | ~5ms | Application startup |
| Auth cache hit | <1ms | JWT validated within 60-second TTL |
| Auth DB queries (cache miss) | 5–10ms | Revocation check + user load |
| Fernet encryption/decryption | <1ms | Credential access |
| bcrypt verify | 50–200ms | Login only (intentional — 12 rounds) |

**Total per-query overhead:** <2ms for provenance across typical 5–15 execution steps.

---

*This document covers the complete security architecture as of May 2026. For implementation details and source references, see the files listed in each section.*
