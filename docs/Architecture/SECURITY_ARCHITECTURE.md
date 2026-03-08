# Uderia Security Architecture

## Executive Summary

Uderia implements two complementary cryptographic security systems that together provide end-to-end trust guarantees no other agentic AI platform offers:

1. **License-Based Prompt Encryption** — Protects the intellectual property embedded in system prompts through a multi-layered encryption architecture with tier-based access control. Ensures that the strategic reasoning instructions powering the platform remain protected during distribution, at rest in the database, and at runtime.

2. **Execution Provenance Chain (EPC)** — Creates an immutable, cryptographically signed audit trail from user query through every LLM decision, tool call, and response. Enables offline verification that no step was injected, tampered with, or replayed. Covers all five execution paths across the platform.

Together, these systems establish a **zero-trust execution model**: the prompts that drive the AI are cryptographically protected, and every action the AI takes is cryptographically recorded. This positions Uderia for enterprise compliance requirements including SOX audit trails, GDPR accountability, and EU AI Act transparency mandates.

---

## Part I: License-Based Prompt Encryption

### 1.1 Problem Statement

System prompts are the core intellectual property of the Uderia platform. They encode strategic planning logic, tactical tool selection heuristics, error recovery strategies, and domain-specific reasoning patterns refined over months of engineering. Without protection:

- Competitors could extract and replicate the platform's reasoning capabilities
- Unauthorized users could view or modify strategic execution logic
- Database exports or backups could leak proprietary prompt content
- Different license tiers could not enforce differentiated access

### 1.2 Architecture Overview

The system uses a **two-layer encryption model** with asymmetric license signing:

```
DEVELOPMENT                    DISTRIBUTION                   RUNTIME

Plain Text Prompts          Bootstrap Encryption          Tier-Based Database
(*.txt files)                  (Public Key)               Encryption (License)
      |                            |                             |
      v                            v                             v
default_prompts/           schema/default_prompts.dat       tda_auth.db
  15 prompt files            86 KB encrypted JSON          (prompts table)
      |                            |                             |
      +-- encrypt_default_prompts.py ---> [bootstrap encrypted] -+
      |                                                          |
      +-- update_prompt.py (for existing installations) ---------+
```

### 1.3 Cryptographic Primitives

| Layer | Algorithm | Key Derivation | Key Size | Salt | Iterations |
|-------|-----------|---------------|----------|------|------------|
| **License Signing** | RSA-PSS (4096-bit) | N/A | 4096 bits | MGF1(SHA-256) | N/A |
| **Bootstrap Encryption** | Fernet (AES-128-CBC + HMAC-SHA256) | PBKDF2-SHA256 | 256 bits | `uderia_bootstrap_prompts_v1` | 100,000 |
| **Database Encryption** | Fernet (AES-128-CBC + HMAC-SHA256) | PBKDF2-SHA256 | 256 bits | `uderia_tier_prompts_v1` | 100,000 |

**Fernet Token Format:**
```
Version (1 byte) | Timestamp (8 bytes) | IV (16 bytes) | Ciphertext | HMAC-SHA256 (32 bytes)
```

Fernet provides authenticated encryption — the HMAC is verified before decryption, preventing padding oracle attacks and ensuring integrity.

### 1.4 License System

#### 1.4.1 Key Pair Generation

A one-time RSA-4096 key pair is generated in the license repository:

```
trusted-data-agent-license/
  private_key.pem    # NEVER distributed (signs licenses)
  public_key.pem     # Shipped with application (verifies signatures)
```

The private key signs license payloads; the public key is distributed with the application for signature verification. The RSA-4096 key size provides security beyond 2030 per NIST guidelines.

#### 1.4.2 License File Structure

```json
{
  "payload": {
    "holder": "customer@company.com",
    "issued_at": "2026-03-06T12:00:00+00:00",
    "expires_at": "2027-03-06T12:00:00+00:00",
    "tier": "Prompt Engineer"
  },
  "signature": "<hex-encoded RSA-PSS signature>"
}
```

**Signature Algorithm:** RSA-PSS with SHA-256 hash, MGF1(SHA-256) mask generation, and maximum salt length. RSA-PSS is preferred over PKCS#1 v1.5 for its provable security reduction.

**Verification at startup:**
1. Load `tda_keys/public_key.pem`
2. Load `tda_keys/license.key`
3. Verify RSA-PSS signature over `json.dumps(payload, sort_keys=True)`
4. Check `expires_at` against current UTC time
5. Store validated payload in `APP_STATE['license_info']`

If verification fails, the application refuses to start.

#### 1.4.3 License Tiers

| Tier | Runtime Decrypt | UI View/Edit | Create Overrides | Key Material |
|------|:-:|:-:|:-:|---|
| **Standard** | Yes | No | No | `signature:Standard:uderia_prompt_encryption_v1` |
| **Prompt Engineer** | Yes | Yes | Profile-level | `signature:Prompt Engineer:uderia_prompt_encryption_v1` |
| **Enterprise** | Yes | Yes | User + Profile | `signature:Enterprise:uderia_prompt_encryption_v1` |

**Key isolation:** Each unique license signature produces a different encryption key. Two customers with different licenses cannot decrypt each other's database content. The tier component ensures that even within a single license, upgrading the tier requires re-encryption.

### 1.5 Key Derivation

#### Bootstrap Key (Distribution Protection)

```python
def derive_bootstrap_key() -> bytes:
    public_key_bytes = read("tda_keys/public_key.pem")  # Raw PEM including headers

    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,                                    # 256-bit Fernet key
        salt=b'uderia_bootstrap_prompts_v1',          # Fixed, deterministic
        iterations=100_000
    )
    return base64.urlsafe_b64encode(kdf.derive(public_key_bytes))
```

**Properties:**
- Deterministic — same key on every installation (all ship with the same `public_key.pem`)
- One-way — cannot recover `public_key.pem` from derived key
- Purpose — IP protection during distribution only; not a security boundary

#### Tier Key (License-Bound Protection)

```python
def derive_tier_key(license_info: dict) -> bytes:
    signature = license_info['signature']          # Hex-encoded RSA-PSS output
    tier = license_info['tier']                     # "Standard" | "Prompt Engineer" | "Enterprise"

    key_material = f"{signature}:{tier}:uderia_prompt_encryption_v1".encode('utf-8')

    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,
        salt=b'uderia_tier_prompts_v1',
        iterations=100_000
    )
    return base64.urlsafe_b64encode(kdf.derive(key_material))
```

**Properties:**
- License-specific — different customers produce different keys
- Tier-aware — same license with different tier produces different key
- Prevents sharing — database content is bound to the specific license that encrypted it
- 100,000 PBKDF2 iterations resist brute-force key recovery

### 1.6 Encryption Flow

#### 1.6.1 Development: Creating Encrypted Distribution

```
default_prompts/WORKFLOW_META_PLANNING_PROMPT.txt
    |
    v  [encrypt_default_prompts.py]
    |
    |  1. Read plain text content
    |  2. derive_bootstrap_key() from public_key.pem
    |  3. Fernet(key).encrypt(content.encode('utf-8'))
    |  4. base64.b64encode(fernet_token)
    |
    v
schema/default_prompts.dat
{
  "WORKFLOW_META_PLANNING_PROMPT": "gAAAAABlXx2V...",
  "MASTER_SYSTEM_PROMPT": "gAAAAABlXx2W...",
  ... (15 prompts total)
}
```

#### 1.6.2 Bootstrap: First Application Start

```
schema/default_prompts.dat
    |
    v  [database.py::_bootstrap_prompt_system()]
    |
    |  1. Load encrypted JSON
    |  2. derive_bootstrap_key() -> bootstrap_key
    |  3. For each prompt:
    |     a. decrypt_prompt(encrypted, bootstrap_key)  -> plain text
    |     b. derive_tier_key(license_info)             -> tier_key
    |     c. encrypt_prompt(plain_text, tier_key)      -> tier_encrypted
    |     d. INSERT INTO prompts (content = tier_encrypted)
    |
    v
tda_auth.db (prompts table: tier-encrypted content)
```

#### 1.6.3 Runtime: Prompt Loading

```
LLM needs system prompt
    |
    v  [prompt_loader.py::get_prompt()]
    |
    |  1. Check cache (hit -> return immediately)
    |  2. Load override hierarchy:
    |     a. User override    (PE/Enterprise only)
    |     b. Profile override (any tier)
    |     c. Base prompt      (from prompts table)
    |  3. decrypt_prompt(encrypted_content, tier_key)
    |  4. Resolve {PARAMETERS} from global_parameters table
    |  5. Cache decrypted result
    |
    v
Decrypted prompt -> LLM provider
```

#### 1.6.4 Deployment: Updating Existing Installations

```
[update_prompt.py --app-root /path/to/uderia --all]
    |
    |  1. Load plain text from default_prompts/*.txt
    |  2. Load license.key from target installation
    |  3. derive_tier_key(license_info)
    |  4. For each prompt:
    |     a. Decrypt existing DB content
    |     b. Compare with new plain text (skip if unchanged)
    |     c. encrypt_prompt(new_content, tier_key)
    |     d. UPDATE prompts SET content = ?, version = version + 1
    |  5. Sync global_parameters from tda_config.json
    |  6. Sync profile_prompt_mappings
    |  7. POST /api/v1/admin/prompts/clear-cache (JWT-authenticated)
    |
    v
Zero-downtime update (no restart required)
```

### 1.7 Prompt Inventory

15 system prompts govern the platform's reasoning:

| Category | Prompt | Purpose |
|----------|--------|---------|
| **System** | `MASTER_SYSTEM_PROMPT` | Core agent persona (OpenAI/Anthropic) |
| **System** | `GOOGLE_MASTER_SYSTEM_PROMPT` | Variant for Google Gemini |
| **System** | `OLLAMA_MASTER_SYSTEM_PROMPT` | Variant for local Ollama models |
| **Planning** | `WORKFLOW_META_PLANNING_PROMPT` | Strategic multi-phase plan decomposition |
| **Planning** | `WORKFLOW_TACTICAL_PROMPT` | Per-phase tool selection |
| **Planning** | `TASK_CLASSIFICATION_PROMPT` | Aggregation vs synthesis classification |
| **Error** | `ERROR_RECOVERY_PROMPT` | Multi-step plan failure recovery |
| **Error** | `TACTICAL_SELF_CORRECTION_PROMPT` | Single tool call correction |
| **Error** | `TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR` | Column-not-found recovery |
| **Error** | `TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR` | Table-not-found recovery |
| **Optimization** | `SQL_CONSOLIDATION_PROMPT` | SQL query consolidation |
| **Execution** | `CONVERSATION_EXECUTION` | Ideate profile (no tools) |
| **Execution** | `CONVERSATION_WITH_TOOLS_EXECUTION` | Ideate profile with MCP tools |
| **Execution** | `GENIE_COORDINATOR_PROMPT` | Coordinate multi-profile orchestration |
| **Execution** | `RAG_FOCUSED_EXECUTION` | Focus profile semantic search |

### 1.8 Business Value

**Intellectual Property Protection:**
- System prompts represent months of engineering effort in strategic planning, error recovery, and tool orchestration
- Encrypted distribution prevents extraction from application packages
- Tier-based access ensures only paying customers can view/modify prompt logic

**License Enforcement:**
- Each license produces a unique encryption key — database content is bound to the specific customer
- Expiration dates enforce renewal cycles
- RSA-PSS signatures prevent license forgery

**Deployment Flexibility:**
- Zero-downtime prompt updates to running installations
- Idempotent deployment script (safe to run multiple times)
- Automatic cache invalidation via REST API

---

## Part II: Execution Provenance Chain (EPC)

### 2.1 Problem Statement

In agentic AI systems, the execution path from user query to final response involves multiple LLM calls, tool selections, and data transformations. Without provenance:

- There is no proof that a specific tool was actually called (vs. fabricated by the LLM)
- Audit trails can be retroactively modified without detection
- Compliance officers cannot verify that the system behaved as claimed
- Cross-session integrity (e.g., genie coordinator delegating to child profiles) is unverifiable
- Replay attacks — injecting pre-computed responses — are undetectable

The EPC solves this by creating a **blockchain-like hash chain** signed with Ed25519 for every execution step, across all five profile types.

### 2.2 Architecture Overview

```
Session Chain (links turns together via cross-turn hashes)
  |
  Turn 1: [query_intake] -> [strategic_plan] -> [tool_call] -> [tool_result] -> [turn_complete]
  |            hash_0    ->      hash_1       ->    hash_2   ->     hash_3    ->     hash_4
  |
  Turn 2: [query_intake] -> [llm_call] -> [llm_response] -> [turn_complete]
               hash_5    ->    hash_6   ->      hash_7     ->     hash_8
               ^
               previous_turn_tip = hash_4  (cross-turn link)
```

**Two levels of chaining:**
1. **Intra-turn** — Steps within a turn are hash-chained sequentially
2. **Cross-turn** — Each turn's first step links to the previous turn's last step via `previous_turn_tip_hash`

This gives full session integrity — tampering with any step in any turn breaks the chain forward.

### 2.3 Cryptographic Primitives

| Component | Algorithm | Key Size | Purpose |
|-----------|-----------|----------|---------|
| **Content Hashing** | SHA-256 | 256 bits | Hash execution content (truncated to 4096 chars) |
| **Chain Hashing** | SHA-256 | 256 bits | Link steps: `SHA256(index:type:content_hash:previous_hash)` |
| **Step Signing** | Ed25519 | 256 bits | Sign each chain_hash for tamper detection |
| **Key Fingerprint** | SHA-256 | 256 bits | Identify which key signed the chain |

**Why Ed25519 over HMAC:**
- Asymmetric — auditors verify with the public key only, never needing the private key
- Compact — 64-byte signatures (vs. variable HMAC output)
- Fast — ~10us per signature operation
- Deterministic — same input always produces same signature (no randomness needed)

### 2.4 Key Management

#### Auto-Generation

On first use, the system auto-generates an Ed25519 key pair:

```
tda_keys/
  provenance_key.pem    # Private key (PKCS8 PEM, 0600 permissions)
  provenance_key.pub    # Public key (SubjectPublicKeyInfo PEM)
```

This follows the same pattern as `jwt_secret.key` — auto-generated on first use, no manual setup required.

#### Key Fingerprint

Every provenance envelope includes the key fingerprint:

```python
fingerprint = SHA256(public_key.public_bytes_raw())  # 64-char hex
```

This allows multi-key verification — after key rotation, old chains remain verifiable by matching the stored fingerprint to the correct public key.

#### Key Rotation

```bash
python maintenance/rotate_provenance_key.py
```

1. Backs up existing keys with timestamp suffix (e.g., `provenance_key.pem.20260306_143000.bak`)
2. Generates new Ed25519 key pair
3. Old chains remain verifiable — each chain stores the `key_fingerprint` used at signing time
4. Application restart loads the new key

#### Degraded Mode

If the signing key is unavailable (permission error, missing file):
- Chain hashes are still computed and recorded
- Signatures are empty strings (`""`)
- Verification reports warnings but can still validate hash integrity
- System continues operating without blocking execution

### 2.5 Chain Structure

#### Step Schema

Each step in the provenance chain:

```json
{
  "step_id": "uuid4",
  "step_index": 0,
  "step_type": "query_intake",
  "timestamp": "2026-03-06T12:00:00.000000+00:00",
  "content_hash": "sha256hex64 (of truncated content)",
  "previous_hash": "sha256hex64 (of prior step's chain_hash, or genesis)",
  "chain_hash": "sha256hex64 (of index:type:content_hash:previous_hash)",
  "signature": "base64(Ed25519(chain_hash))",
  "content_summary": "Human-readable summary (max 200 chars)"
}
```

#### Chain Hash Computation

```
chain_hash = SHA256("{step_index}:{step_type}:{content_hash}:{previous_hash}")
```

This binds the step's position, type, content, and predecessor into a single hash. Changing any field invalidates the chain_hash, and since subsequent steps reference it as `previous_hash`, tampering is detectable at any depth.

#### Content Hashing

```
content_hash = SHA256(content[:4096])
```

- Content is hashed, **never stored** — no sensitive data in the provenance record
- 4096-character truncation bounds overhead for large tool results
- Content summaries (max 200 chars) provide human-readable context without exposing full data

#### Genesis Hash

The first step of the first turn uses the genesis hash:

```
GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"
```

#### Provenance Envelope

After a turn completes, the chain is sealed into an envelope:

```json
{
  "provenance_chain": [ ...steps... ],
  "provenance_meta": {
    "chain_version": 1,
    "key_fingerprint": "sha256hex64",
    "profile_type": "tool_enabled",
    "session_id": "uuid",
    "turn_number": 1,
    "user_uuid": "uuid",
    "step_count": 8,
    "chain_root_hash": "sha256hex64 (first step)",
    "chain_tip_hash": "sha256hex64 (last step)",
    "previous_turn_tip_hash": null,
    "sealed": true
  }
}
```

The envelope is merged into the turn's `workflow_history` entry via `turn_summary.update(chain.finalize())`.

### 2.6 Step Type Taxonomy

#### Universal (All Profiles)

| Step Type | Content Hashed | When |
|-----------|---------------|------|
| `query_intake` | `user_input` | Start of every execution |
| `profile_resolve` | `profile_id:profile_type:profile_tag` | After profile resolved |
| `llm_response` | `response_text[:4096]` | After each LLM call |
| `turn_complete` | `final_summary_text` | End of turn (success) |
| `error:cancelled` | `cancellation_reason` | User cancels mid-execution |
| `error:llm_error` | `error_message` | LLM provider failure |
| `error:tool_error` | `error_message` | Tool execution failure |
| `error:system_error` | `error_message` | Unexpected system error |

#### Optimize (tool_enabled)

| Step Type | Content Hashed | When |
|-----------|---------------|------|
| `strategic_plan` | `json.dumps(meta_plan, sort_keys=True)` | After planner returns plan |
| `plan_rewrite` | `pass_name:json.dumps(plan_after)` | After each rewrite pass that modifies plan |
| `tactical_decision` | `phase_idx:tool_name:json.dumps(args)` | After tactical tool selection |
| `tool_call` | `tool_name:json.dumps(args, sort_keys=True)` | Before MCP execution |
| `tool_result` | `tool_name:result[:4096]` | After MCP returns |
| `self_correction` | `attempt:error:corrected_args` | When self-correction fires |
| `synthesis` | `synthesis_input[:4096]` | Before final answer LLM call |

#### Ideate (llm_only)

| Step Type | Content Hashed | When |
|-----------|---------------|------|
| `knowledge_retrieval` | `json.dumps({"collections": ids, "doc_count": n})` | After knowledge fetch |
| `llm_call` | `sha256(system_prompt):sha256(user_message)` | Before LLM call |

#### Focus (rag_focused)

| Step Type | Content Hashed | When |
|-----------|---------------|------|
| `rag_search` | `json.dumps(collection_ids)` | Semantic search invoked |
| `rag_results` | `json.dumps({"doc_ids": [...], "scores": [...]})` | Results returned |
| `rag_synthesis` | `synthesis_prompt[:4096]` | Before synthesis LLM call |

#### Ideate + MCP (conversation_with_tools)

| Step Type | Content Hashed | When |
|-----------|---------------|------|
| `agent_tool_call` | `tool_name:json.dumps(args)` | LangChain `on_tool_start` |
| `agent_tool_result` | `tool_name:result[:4096]` | LangChain `on_tool_end` |
| `agent_llm_step` | `step_name:token_count` | LangChain `on_llm_end` |

#### Coordinate (genie)

| Step Type | Content Hashed | When |
|-----------|---------------|------|
| `coordinator_dispatch` | `child_profile_tag:delegated_query` | Child profile invoked |
| `child_chain_ref` | `child_session_id:child_chain_tip_hash` | Child completes (cross-session link) |
| `coordinator_synthesis` | `coordinator_output[:4096]` | Final synthesis |

### 2.7 Cross-Session Linking (Genie)

The Coordinate profile (genie) delegates work to child profiles, each running in their own session. The EPC creates a **Merkle-tree-like structure** across sessions:

```
Parent Session (genie)
  |
  [coordinator_dispatch] -> "Delegating to @OPTIM: Show databases"
  |
  +-- Child Session (@OPTIM)
  |     [query_intake] -> [strategic_plan] -> [tool_call] -> [turn_complete]
  |                                                               |
  |     chain_tip_hash = abc123...                               |
  |                                                               |
  [child_chain_ref] -> "child_session_id:abc123..."  <-----------+
  |
  [coordinator_dispatch] -> "Delegating to @FOCUS: Search docs"
  |
  +-- Child Session (@FOCUS)
  |     [query_intake] -> [rag_search] -> [rag_results] -> [turn_complete]
  |     chain_tip_hash = def456...
  |
  [child_chain_ref] -> "child_session_id:def456..."
  |
  [coordinator_synthesis] -> "Combined answer from both profiles"
  [turn_complete]
```

**Implementation:** A module-level `_provenance_chains` registry (keyed by parent session ID) allows the `SlaveSessionTool` (a Pydantic `BaseTool`) to access the parent's provenance chain for recording `coordinator_dispatch` and `child_chain_ref` steps.

### 2.8 Verification

Three verification levels, each building on the previous:

#### Level 1: Chain Integrity (Offline-Capable)

```python
verify_chain(provenance_data, public_key_pem=None) -> {
    "valid": bool | None,
    "errors": [...],
    "warnings": [...],
    "step_count": int
}
```

Three checks per step:
1. **Chain linking** — `step.previous_hash` matches prior step's `chain_hash`
2. **Hash computation** — `chain_hash == SHA256(index:type:content_hash:previous_hash)`
3. **Signature** — `Ed25519.verify(signature, chain_hash)` using public key

Plus meta consistency:
- `chain_tip_hash` matches last step's `chain_hash`
- `chain_root_hash` matches first step's `chain_hash`
- `step_count` matches actual chain length

**Offline-capable:** Only requires the public key PEM — no network access, no database, no running application.

#### Level 2: Content Verification

```python
verify_content(provenance_data, turn_data) -> {
    "valid": bool | None,
    "verified": int,
    "mismatches": [...],
    "skipped": int
}
```

Maps step types to actual session data and recomputes content hashes:
- `query_intake` -> `SHA256(turn_data["user_query"])`
- `strategic_plan` -> `SHA256(json.dumps(turn_data["raw_llm_plan"]))`
- `turn_complete` -> `SHA256(turn_data["final_summary"])`

Steps without stored content references (tool calls, errors) are skipped.

#### Level 3: Session Integrity

```python
verify_session(user_uuid, session_id, public_key_pem=None) -> {
    "valid": bool | None,
    "turns_verified": int,
    "turns_skipped": int,
    "errors": [...]
}
```

Verifies all turns in a session:
1. Each turn's chain is independently valid (Level 1)
2. Each turn's `previous_turn_tip_hash` matches prior turn's `chain_tip_hash`
3. Turns without provenance data are skipped (backward compatibility)

### 2.9 REST API

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/v1/sessions/{id}/provenance` | Full provenance for all turns |
| `GET` | `/api/v1/sessions/{id}/provenance/turn/{turn}` | Single turn's chain |
| `POST` | `/api/v1/sessions/{id}/provenance/verify` | Verify integrity (L1 + L3) |
| `GET` | `/api/v1/sessions/{id}/provenance/export` | Download JSON for offline audit |
| `GET` | `/api/v1/provenance/public-key` | Download public key PEM |

All endpoints require JWT authentication. Session ownership is enforced — users can only access their own sessions.

**Offline Audit Workflow:**
1. Download provenance export: `GET /sessions/{id}/provenance/export`
2. Download public key: `GET /provenance/public-key`
3. Verify independently using `verify_chain()` with the downloaded public key
4. No network access or running application required

### 2.10 Error and Cancellation Handling

Execution can fail at any point. The chain handles this gracefully:

**Error steps:** Before sealing, an `error:{type}` step is recorded:
```python
chain.add_error_step("llm_error", "Provider returned 429 rate limit")
```

**Cancellation:** When the user cancels mid-execution:
```python
chain.add_error_step("cancelled", "User cancelled execution")
```

**Partial turns:** The chain is always finalized in a `finally` block, even on error. Partial turns (status="error") include the provenance chain with fewer steps, ending with the error step.

**Sealed chain guarantee:** Once `finalize()` is called, no more steps can be added. Attempting to add a step to a sealed chain logs a warning and returns an empty dict.

### 2.11 Backward Compatibility

- **Existing sessions:** `verify_chain()` returns `{"valid": None, "warnings": ["No provenance data"]}` for turns without provenance
- **verify_session()** skips turns without `provenance_chain` field
- **REST API** returns `{"provenance": null, "message": "No provenance data for this turn"}` for old turns
- **Cross-turn linking:** `get_previous_turn_tip_hash()` returns `None` for sessions with no provenance — first turn uses the genesis hash

### 2.12 Business Value

**Enterprise Compliance:**
- **SOX (Sarbanes-Oxley):** Immutable audit trail of every AI-driven financial decision
- **GDPR Article 22:** Verifiable record of automated decision-making processes
- **EU AI Act (2026):** Transparency requirements for high-risk AI systems
- **ISO 27001:** Evidence of information security controls in AI operations

**Competitive Differentiation:**
No agentic AI platform currently offers cryptographically signed execution provenance. This is a first-of-its-kind capability that:
- Proves execution integrity to auditors without exposing sensitive data
- Enables offline verification with just a public key
- Creates cross-session Merkle-tree structures for multi-agent coordination
- Supports key rotation without invalidating historical chains

**Operational Benefits:**
- Tamper detection — any modification to session data is immediately detectable
- Forensic analysis — trace exactly which tools were called with which arguments
- Debugging — provenance chains provide a precise execution timeline
- Accountability — every step is timestamped and signed

---

## Part III: Combined Security Model

### 3.1 End-to-End Trust Chain

The two systems complement each other to create a complete trust model:

```
+-----------------------------------------------------------------+
|                    PROMPT ENCRYPTION                              |
|  Protects: What the AI is instructed to do                       |
|  Guarantees: Only authorized prompts reach the LLM               |
|  Verification: License signature + tier-based decryption          |
+-----------------------------------------------------------------+
                              |
                              | (encrypted prompts drive execution)
                              v
+-----------------------------------------------------------------+
|                 EXECUTION PROVENANCE CHAIN                        |
|  Protects: What the AI actually did                              |
|  Guarantees: Every action is recorded and tamper-evident          |
|  Verification: Hash chains + Ed25519 signatures                  |
+-----------------------------------------------------------------+
```

**Together they answer two critical questions:**
1. **Were the correct instructions used?** — Prompt encryption ensures only authorized, license-validated prompts drive execution
2. **Did the system follow those instructions faithfully?** — The EPC proves every step from query to response was actually executed as recorded

### 3.2 Key Inventory

All cryptographic keys reside in `tda_keys/`:

| File | Algorithm | Purpose | Auto-Generated | Rotation |
|------|-----------|---------|:-:|---|
| `public_key.pem` | RSA-4096 | License verification + bootstrap key derivation | No (shipped) | Requires new licenses |
| `license.key` | RSA-PSS signed JSON | License validation + tier key derivation | No (issued) | New license file |
| `jwt_secret.key` | HMAC-SHA256 | JWT session tokens | Yes | `maintenance/regenerate_jwt_secret.py` |
| `provenance_key.pem` | Ed25519 | EPC chain signing (private) | Yes | `maintenance/rotate_provenance_key.py` |
| `provenance_key.pub` | Ed25519 | EPC chain verification (public) | Yes | Rotated with private key |

### 3.3 Zero New Dependencies

Both security systems use the `cryptography` library already present in the project:
- **Prompt encryption:** `cryptography.fernet`, `cryptography.hazmat.primitives.kdf.pbkdf2`, RSA
- **Provenance chain:** `cryptography.hazmat.primitives.asymmetric.ed25519`
- **Standard library:** `hashlib` (SHA-256), `base64`, `json`, `uuid`

### 3.4 Performance Impact

| Operation | Latency | When |
|-----------|---------|------|
| Prompt decryption | <10ms per prompt | First load (cached thereafter) |
| Bootstrap re-encryption | ~2-3s for 15 prompts | One-time on first start |
| Provenance step (hash + sign) | ~100us | Per execution step |
| Chain verification (L1) | ~1ms per step | On-demand via REST API |
| License verification | ~5ms | Application startup |

**Total overhead per query:** <1ms for provenance (typically 5-15 steps at ~100us each). Negligible compared to LLM latency (2-12 seconds).

### 3.5 Threat Model

| Threat | Prompt Encryption | Execution Provenance |
|--------|:-:|:-:|
| Unauthorized prompt viewing | Mitigated (tier-based encryption) | N/A |
| Prompt tampering in database | Detected (Fernet HMAC) | N/A |
| License forgery | Mitigated (RSA-PSS 4096-bit) | N/A |
| Execution log tampering | N/A | Detected (hash chain + Ed25519) |
| Step injection (adding fake steps) | N/A | Detected (chain linking) |
| Step removal (hiding actions) | N/A | Detected (step_count + chain break) |
| Replay attack (reusing old responses) | N/A | Detected (timestamps + chain context) |
| Cross-session tampering (genie) | N/A | Detected (child_chain_ref linking) |
| Key compromise | Re-issue license | Rotate key (old chains stay valid) |
| Man-in-the-middle (LLM provider) | N/A | Content hashes detect response substitution |

### 3.6 Compliance Mapping

| Regulation | Requirement | Uderia Capability |
|------------|------------|-------------------|
| **EU AI Act** | Transparency of AI decision-making | EPC records every LLM call, tool selection, and response |
| **EU AI Act** | Logging and traceability for high-risk AI | Immutable, signed provenance chains with offline verification |
| **GDPR Art. 22** | Right to explanation of automated decisions | Provenance chain traces from query to final answer |
| **GDPR Art. 30** | Records of processing activities | Session-level provenance with cross-turn integrity |
| **SOX** | Internal controls over financial reporting | Tamper-evident audit trail for AI-assisted financial operations |
| **ISO 27001** | Information security management | Encrypted prompts, signed execution logs, key management |
| **NIST AI RMF** | AI risk management framework | Content hashing (no sensitive data stored), offline verification |

---

## Part IV: Implementation Reference

### 4.1 File Inventory

#### Prompt Encryption Files

| File | Repository | Purpose | Lines |
|------|-----------|---------|-------|
| `src/trusted_data_agent/agent/prompt_encryption.py` | uderia | Core encryption utilities | ~236 |
| `src/trusted_data_agent/agent/prompt_loader.py` | uderia | Database-backed prompt loading | ~400 |
| `src/trusted_data_agent/auth/database.py` | uderia | Bootstrap process | ~1800 |
| `encrypt_default_prompts.py` | license | Generate `default_prompts.dat` | ~173 |
| `update_prompt.py` | license | Zero-downtime deployment | ~547 |
| `generate_keys.py` | license | RSA key pair generation | ~50 |
| `generate_license.py` | license | License file creation | ~80 |
| `schema/default_prompts.dat` | uderia | Encrypted distribution file | ~86KB |

#### Execution Provenance Files

| File | Purpose | Lines |
|------|---------|-------|
| `src/trusted_data_agent/core/provenance.py` | ProvenanceChain, key mgmt, verification | ~500 |
| `src/trusted_data_agent/api/provenance_routes.py` | REST API endpoints | ~196 |
| `maintenance/rotate_provenance_key.py` | Key rotation utility | ~79 |

#### Modified Files (EPC Integration)

| File | Changes |
|------|---------|
| `src/trusted_data_agent/agent/executor.py` | Chain init + instrumentation for all 4 non-genie profiles |
| `src/trusted_data_agent/agent/planner.py` | `plan_rewrite` steps |
| `src/trusted_data_agent/agent/phase_executor.py` | `tactical_decision`, `tool_call`, `tool_result`, `self_correction` |
| `src/trusted_data_agent/agent/conversation_agent.py` | `agent_tool_call`, `agent_tool_result` |
| `src/trusted_data_agent/agent/execution_service.py` | Genie chain init + finalization |
| `src/trusted_data_agent/agent/genie_coordinator.py` | `coordinator_dispatch`, `child_chain_ref` |
| `src/trusted_data_agent/main.py` | Blueprint registration |

### 4.2 Testing

#### Prompt Encryption

```bash
# Run encryption test suite
cd uderia/schema
python dev/test_prompt_encryption.py
```

#### Execution Provenance

```bash
# Verify chain creation and tamper detection
python3 -c "
from trusted_data_agent.core.provenance import ProvenanceChain, verify_chain

# Create and seal a chain
chain = ProvenanceChain('test-session', 1, 'test-user', 'tool_enabled')
chain.add_step('query_intake', 'Show me all products', 'User query')
chain.add_step('tool_call', 'base_readQuery:SELECT * FROM products', 'Calling base_readQuery')
chain.add_step('turn_complete', 'Found 15 products', 'Turn complete')
envelope = chain.finalize()

# Verify integrity
result = verify_chain(envelope)
print(f'Valid: {result[\"valid\"]}')  # True
print(f'Steps: {result[\"step_count\"]}')  # 3

# Tamper test
envelope['provenance_chain'][1]['content_hash'] = 'tampered'
result = verify_chain(envelope)
print(f'After tamper: {result[\"valid\"]}')  # False
print(f'Errors: {result[\"errors\"]}')
"
```

#### REST API Verification

```bash
# Start server
python -m trusted_data_agent.main &

# Authenticate
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

# Create session + submit query (provenance is auto-generated)
SESSION_ID=$(curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{}' | jq -r '.session_id')

TASK_ID=$(curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/query \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"prompt": "What is 2+2?"}' | jq -r '.task_id')

sleep 10  # Wait for execution

# Verify provenance
curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION_ID/provenance/verify \
  -H "Authorization: Bearer $JWT" | jq .

# Export for offline audit
curl -s http://localhost:5050/api/v1/sessions/$SESSION_ID/provenance/export \
  -H "Authorization: Bearer $JWT" -o provenance_export.json

# Download public key
curl -s http://localhost:5050/api/v1/provenance/public-key \
  -H "Authorization: Bearer $JWT" | jq .
```

---

## Appendix A: Cryptographic Algorithm Selection Rationale

### Ed25519 for Provenance (vs. alternatives)

| Criterion | Ed25519 | RSA-2048 | HMAC-SHA256 | ECDSA P-256 |
|-----------|:-------:|:--------:|:-----------:|:-----------:|
| Asymmetric (offline verify) | Yes | Yes | No | Yes |
| Signature size | 64 bytes | 256 bytes | 32 bytes | 64 bytes |
| Sign speed | ~10us | ~1ms | ~1us | ~100us |
| Verify speed | ~30us | ~50us | ~1us | ~200us |
| Key size | 32 bytes | 256 bytes | 32 bytes | 32 bytes |
| Deterministic | Yes | No | Yes | No |
| Side-channel resistant | Yes (by design) | Requires care | Yes | Requires care |

**Decision:** Ed25519 provides the best balance of security, performance, and offline verification capability. HMAC would require sharing the secret key with auditors.

### Fernet for Prompt Encryption (vs. alternatives)

| Criterion | Fernet (AES-128-CBC) | AES-256-GCM | ChaCha20-Poly1305 |
|-----------|:---:|:---:|:---:|
| Authenticated encryption | Yes (HMAC) | Yes (GCM tag) | Yes (Poly1305) |
| Python library support | `cryptography.fernet` | Manual construction | Manual construction |
| Timestamp included | Yes | No | No |
| Key derivation built-in | No (separate PBKDF2) | No | No |
| Simplicity | High (one-liner API) | Medium | Medium |

**Decision:** Fernet provides authenticated encryption with a simple, hard-to-misuse API. The 128-bit AES key is sufficient for IP protection (not military-grade secrets). The timestamp field enables future token expiration if needed.

### RSA-4096 for License Signing (vs. alternatives)

| Criterion | RSA-4096/PSS | Ed25519 | ECDSA P-384 |
|-----------|:---:|:---:|:---:|
| NIST approved | Yes | Yes (EdDSA) | Yes |
| Widely understood | Yes | Growing | Yes |
| Key derivation from signature | Good (512-byte signature = high entropy) | Poor (64-byte signature) | Moderate |
| Library maturity | Excellent | Excellent | Excellent |

**Decision:** RSA-4096 with PSS padding provides a large signature (512 bytes) that serves double duty as high-entropy input for PBKDF2 key derivation. The signature's size ensures excellent key material for the tier-specific encryption keys.

---

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **Bootstrap key** | Fernet key derived from `public_key.pem` via PBKDF2; decrypts `default_prompts.dat` |
| **Chain hash** | SHA-256 hash linking a step to its position, type, content, and predecessor |
| **Content hash** | SHA-256 of the actual execution content (truncated to 4096 chars) |
| **Cross-turn link** | First step of turn N references `chain_tip_hash` of turn N-1 |
| **Degraded mode** | EPC records hashes but not signatures (signing key unavailable) |
| **EPC** | Execution Provenance Chain — the cryptographic audit trail system |
| **Fernet** | Symmetric authenticated encryption scheme (AES-128-CBC + HMAC-SHA256) |
| **Genesis hash** | 64 zero characters; used as `previous_hash` for the very first step |
| **Key fingerprint** | SHA-256 of the Ed25519 public key's raw bytes; identifies the signing key |
| **PBKDF2** | Password-Based Key Derivation Function 2; stretches input into encryption keys |
| **Provenance envelope** | The sealed `{provenance_chain, provenance_meta}` dict stored per turn |
| **RSA-PSS** | Probabilistic Signature Scheme; provably secure RSA signature padding |
| **Tier key** | Fernet key derived from license signature + tier via PBKDF2; encrypts database prompts |
| **Turn tip** | The `chain_hash` of the last step in a turn; referenced by the next turn's first step |
