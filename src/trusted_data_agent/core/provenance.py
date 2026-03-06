"""
Execution Provenance Chain (EPC) — Cryptographically signed audit trail.

Creates an immutable, tamper-evident record of every execution step in the
Uderia pipeline. Each step is hash-chained to its predecessor and signed
with Ed25519, enabling offline verification with just the public key.

Two levels of chaining:
  - Intra-turn: steps within a turn link sequentially
  - Cross-turn: each turn's first step links to the previous turn's tip hash
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger("quart.app")

# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

_provenance_key: Optional[Ed25519PrivateKey] = None
_KEY_DIR_NAME = "tda_keys"
_PRIVATE_KEY_FILE = "provenance_key.pem"
_PUBLIC_KEY_FILE = "provenance_key.pub"


def _get_keys_dir() -> str:
    """Return the absolute path to the tda_keys directory."""
    # Walk up from this file to find the project root (where tda_keys lives)
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        candidate = os.path.join(current, _KEY_DIR_NAME)
        if os.path.isdir(candidate):
            return candidate
        current = os.path.dirname(current)
    # Fallback: next to the working directory
    return os.path.join(os.getcwd(), _KEY_DIR_NAME)


def _get_provenance_signing_key() -> Optional[Ed25519PrivateKey]:
    """Load or auto-generate the Ed25519 provenance signing key."""
    global _provenance_key
    if _provenance_key is not None:
        return _provenance_key

    keys_dir = _get_keys_dir()
    private_path = os.path.join(keys_dir, _PRIVATE_KEY_FILE)
    public_path = os.path.join(keys_dir, _PUBLIC_KEY_FILE)

    if os.path.exists(private_path):
        try:
            with open(private_path, "rb") as f:
                _provenance_key = serialization.load_pem_private_key(f.read(), password=None)
            logger.info("[EPC] Loaded provenance signing key from %s", private_path)
            return _provenance_key
        except Exception as e:
            logger.error("[EPC] Failed to load provenance key: %s", e)
            return None

    # Auto-generate on first use
    try:
        os.makedirs(keys_dir, exist_ok=True)
        key = Ed25519PrivateKey.generate()

        # Write private key
        pem_private = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(private_path, "wb") as f:
            f.write(pem_private)
        os.chmod(private_path, 0o600)

        # Write public key
        pem_public = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        with open(public_path, "wb") as f:
            f.write(pem_public)

        _provenance_key = key
        logger.info("[EPC] Generated new provenance key pair at %s", keys_dir)
        return _provenance_key
    except Exception as e:
        logger.warning("[EPC] Failed to generate provenance key — running in degraded mode: %s", e)
        return None


def get_provenance_public_key_pem() -> Optional[bytes]:
    """Return the public key PEM bytes for distribution to auditors."""
    keys_dir = _get_keys_dir()
    public_path = os.path.join(keys_dir, _PUBLIC_KEY_FILE)
    if os.path.exists(public_path):
        with open(public_path, "rb") as f:
            return f.read()
    # If only private key exists, derive public
    key = _get_provenance_signing_key()
    if key:
        return key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    return None


def get_key_fingerprint() -> Optional[str]:
    """SHA256 fingerprint of the public key raw bytes."""
    key = _get_provenance_signing_key()
    if key is None:
        return None
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Cross-turn linking
# ---------------------------------------------------------------------------

async def get_previous_turn_tip_hash(user_uuid: str, session_id: str) -> Optional[str]:
    """Read the last turn's provenance_meta.chain_tip_hash from the session file.

    Returns None if no previous turn or no provenance data (backward compat).
    """
    try:
        from trusted_data_agent.core import session_manager
        session_data = await session_manager.get_session(user_uuid, session_id)
        if not session_data:
            return None
        last_turn = session_data.get("last_turn_data", {})
        workflow = last_turn.get("workflow_history", [])
        if not workflow:
            return None
        latest = workflow[-1]
        meta = latest.get("provenance_meta")
        if meta:
            return meta.get("chain_tip_hash")
        return None
    except Exception as e:
        logger.debug("[EPC] Could not read previous turn tip: %s", e)
        return None


# ---------------------------------------------------------------------------
# ProvenanceChain
# ---------------------------------------------------------------------------

GENESIS_HASH = "0" * 64
CONTENT_MAX_LEN = 4096


class ProvenanceChain:
    """Cryptographically signed execution provenance chain for a single turn."""

    def __init__(
        self,
        session_id: str,
        turn_number: int,
        user_uuid: str,
        profile_type: str,
        previous_turn_tip_hash: Optional[str] = None,
        event_queue: Optional[asyncio.Queue] = None,
    ):
        self.steps: List[Dict[str, Any]] = []
        self.session_id = session_id
        self.turn_number = turn_number
        self.user_uuid = user_uuid
        self.profile_type = profile_type
        self.previous_turn_tip_hash = previous_turn_tip_hash
        self._signing_key = _get_provenance_signing_key()
        self._event_queue = event_queue
        self._sealed = False

    # -- Core operations ---------------------------------------------------

    def add_step(self, step_type: str, content: str, content_summary: str = "") -> dict:
        """Add a signed step to the chain. Returns the step dict.

        Safe to call even if signing key is unavailable (degraded mode —
        hashes recorded but signatures empty).
        """
        if self._sealed:
            logger.warning("[EPC] Attempted to add step to sealed chain — ignored")
            return {}

        step_index = len(self.steps)
        content_for_hash = (content or "")[:CONTENT_MAX_LEN]
        content_hash = hashlib.sha256(content_for_hash.encode("utf-8")).hexdigest()

        # Chain link
        if step_index == 0:
            previous_hash = self.previous_turn_tip_hash or GENESIS_HASH
        else:
            previous_hash = self.steps[-1]["chain_hash"]

        chain_input = f"{step_index}:{step_type}:{content_hash}:{previous_hash}"
        chain_hash = hashlib.sha256(chain_input.encode("utf-8")).hexdigest()

        signature = self._sign(chain_hash)

        step = {
            "step_id": str(_uuid.uuid4()),
            "step_index": step_index,
            "step_type": step_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content_hash": content_hash,
            "previous_hash": previous_hash,
            "chain_hash": chain_hash,
            "signature": signature,
            "content_summary": (content_summary or "")[:200],
        }
        self.steps.append(step)

        # Queue SSE event (non-blocking, drop on full)
        if self._event_queue is not None:
            try:
                self._event_queue.put_nowait({
                    "step_index": step_index,
                    "step_type": step_type,
                    "content_summary": step["content_summary"],
                    "chain_hash": chain_hash,
                })
            except asyncio.QueueFull:
                pass

        return step

    def add_error_step(self, error_type: str, error_message: str) -> dict:
        """Record an error or cancellation before sealing."""
        return self.add_step(
            step_type=f"error:{error_type}",
            content=(error_message or "")[:CONTENT_MAX_LEN],
            content_summary=f"Error: {(error_message or '')[:100]}",
        )

    def finalize(self) -> dict:
        """Seal the chain and return the provenance envelope.

        The returned dict should be merged into the turn_summary via
        ``turn_summary.update(chain.finalize())``.
        """
        self._sealed = True
        fingerprint = get_key_fingerprint()
        return {
            "provenance_chain": self.steps,
            "provenance_meta": {
                "chain_version": 1,
                "key_fingerprint": fingerprint,
                "profile_type": self.profile_type,
                "session_id": self.session_id,
                "turn_number": self.turn_number,
                "user_uuid": self.user_uuid,
                "step_count": len(self.steps),
                "chain_root_hash": self.steps[0]["chain_hash"] if self.steps else None,
                "chain_tip_hash": self.steps[-1]["chain_hash"] if self.steps else None,
                "previous_turn_tip_hash": self.previous_turn_tip_hash,
                "sealed": True,
            },
        }

    # -- Internal ----------------------------------------------------------

    def _sign(self, chain_hash: str) -> str:
        if self._signing_key is None:
            return ""  # Degraded mode
        try:
            sig = self._signing_key.sign(chain_hash.encode("utf-8"))
            return base64.b64encode(sig).decode("ascii")
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _load_public_key(pem: Optional[bytes] = None) -> Optional[Ed25519PublicKey]:
    """Load public key from PEM bytes or from the default key file."""
    if pem:
        return serialization.load_pem_public_key(pem)
    pem_bytes = get_provenance_public_key_pem()
    if pem_bytes:
        return serialization.load_pem_public_key(pem_bytes)
    return None


def verify_chain(provenance_data: dict, public_key_pem: Optional[bytes] = None) -> dict:
    """Level 1: Verify chain integrity (offline-capable).

    Checks per step:
      1. Chain linking — previous_hash matches prior step's chain_hash
      2. Hash computation — chain_hash == SHA256(index:type:content_hash:previous_hash)
      3. Ed25519 signature verification

    Returns:
        {"valid": bool|None, "errors": [...], "warnings": [...], "step_count": int}
    """
    chain = provenance_data.get("provenance_chain")
    meta = provenance_data.get("provenance_meta")

    if not chain or not meta:
        return {"valid": None, "errors": [], "warnings": ["No provenance data"], "step_count": 0}

    public_key = _load_public_key(public_key_pem)
    errors: List[str] = []
    warnings: List[str] = []

    if not public_key:
        warnings.append("No public key available — signature verification skipped")

    prev_turn_tip = meta.get("previous_turn_tip_hash") or GENESIS_HASH

    for i, step in enumerate(chain):
        # 1. Chain linking
        if i == 0:
            expected_prev = prev_turn_tip
        else:
            expected_prev = chain[i - 1]["chain_hash"]

        if step.get("previous_hash") != expected_prev:
            errors.append(f"Step {i} ({step.get('step_type')}): broken chain link — "
                          f"expected previous_hash {expected_prev[:16]}..., "
                          f"got {step.get('previous_hash', 'missing')[:16]}...")

        # 2. Hash computation
        chain_input = f"{step['step_index']}:{step['step_type']}:{step['content_hash']}:{step['previous_hash']}"
        expected_hash = hashlib.sha256(chain_input.encode("utf-8")).hexdigest()
        if step.get("chain_hash") != expected_hash:
            errors.append(f"Step {i} ({step.get('step_type')}): chain_hash mismatch")

        # 3. Signature
        sig_b64 = step.get("signature", "")
        if public_key and sig_b64:
            try:
                sig_bytes = base64.b64decode(sig_b64)
                public_key.verify(sig_bytes, step["chain_hash"].encode("utf-8"))
            except InvalidSignature:
                errors.append(f"Step {i} ({step.get('step_type')}): invalid signature")
            except Exception as e:
                errors.append(f"Step {i} ({step.get('step_type')}): signature check error — {e}")
        elif public_key and not sig_b64:
            warnings.append(f"Step {i} ({step.get('step_type')}): unsigned (degraded mode)")

    # Validate meta consistency
    if chain and meta.get("chain_tip_hash") != chain[-1].get("chain_hash"):
        errors.append("provenance_meta.chain_tip_hash does not match last step")
    if chain and meta.get("chain_root_hash") != chain[0].get("chain_hash"):
        errors.append("provenance_meta.chain_root_hash does not match first step")
    if meta.get("step_count") != len(chain):
        errors.append(f"provenance_meta.step_count ({meta.get('step_count')}) != actual ({len(chain)})")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "step_count": len(chain),
    }


def verify_content(provenance_data: dict, turn_data: dict) -> dict:
    """Level 2: Verify content hashes match actual session data.

    Maps step_type to turn_data fields and compares SHA256 hashes.

    Returns:
        {"valid": bool|None, "verified": int, "mismatches": [...], "skipped": int}
    """
    chain = provenance_data.get("provenance_chain")
    if not chain:
        return {"valid": None, "verified": 0, "mismatches": [], "skipped": 0}

    mismatches: List[str] = []
    verified = 0
    skipped = 0

    for step in chain:
        st = step.get("step_type", "")
        expected_hash = step.get("content_hash")

        actual_content: Optional[str] = None

        if st == "query_intake":
            actual_content = turn_data.get("user_query", "")
        elif st == "strategic_plan":
            raw = turn_data.get("raw_llm_plan")
            if raw is not None:
                actual_content = json.dumps(raw, sort_keys=True, default=str)
        elif st == "turn_complete":
            actual_content = turn_data.get("final_summary", "")
        elif st.startswith("error:"):
            skipped += 1
            continue
        else:
            # Types that require execution_trace correlation or are structural
            skipped += 1
            continue

        if actual_content is not None:
            content_for_hash = actual_content[:CONTENT_MAX_LEN]
            actual_hash = hashlib.sha256(content_for_hash.encode("utf-8")).hexdigest()
            if actual_hash == expected_hash:
                verified += 1
            else:
                mismatches.append(
                    f"Step {step['step_index']} ({st}): content hash mismatch"
                )
        else:
            skipped += 1

    return {
        "valid": len(mismatches) == 0 if verified > 0 else None,
        "verified": verified,
        "mismatches": mismatches,
        "skipped": skipped,
    }


async def verify_session(user_uuid: str, session_id: str,
                         public_key_pem: Optional[bytes] = None) -> dict:
    """Level 3: Verify all turns in a session including cross-turn links.

    Returns:
        {"valid": bool, "turns_verified": int, "turns_skipped": int, "errors": [...]}
    """
    try:
        from trusted_data_agent.core import session_manager
        session_data = await session_manager.get_session(user_uuid, session_id)
    except Exception as e:
        return {"valid": False, "turns_verified": 0, "turns_skipped": 0,
                "errors": [f"Failed to load session: {e}"]}

    if not session_data:
        return {"valid": False, "turns_verified": 0, "turns_skipped": 0,
                "errors": ["Session not found"]}

    last_turn = session_data.get("last_turn_data", {})
    workflow = last_turn.get("workflow_history", [])
    if not workflow:
        return {"valid": None, "turns_verified": 0, "turns_skipped": 0,
                "errors": [], "warnings": ["No workflow history"]}

    errors: List[str] = []
    verified = 0
    skipped = 0
    prev_tip: Optional[str] = None

    for turn in workflow:
        chain_data = {
            "provenance_chain": turn.get("provenance_chain"),
            "provenance_meta": turn.get("provenance_meta"),
        }
        if not chain_data["provenance_chain"]:
            skipped += 1
            continue

        # Verify chain integrity
        result = verify_chain(chain_data, public_key_pem)
        if result.get("valid") is False:
            turn_num = turn.get("turn", "?")
            errors.extend([f"Turn {turn_num}: {e}" for e in result["errors"]])

        # Verify cross-turn link
        meta = chain_data.get("provenance_meta", {})
        stored_prev = meta.get("previous_turn_tip_hash")
        if prev_tip is not None and stored_prev != prev_tip:
            turn_num = turn.get("turn", "?")
            errors.append(
                f"Turn {turn_num}: cross-turn link broken — "
                f"expected {prev_tip[:16]}..., got {(stored_prev or 'None')[:16]}..."
            )

        prev_tip = meta.get("chain_tip_hash")
        verified += 1

    return {
        "valid": len(errors) == 0 if verified > 0 else None,
        "turns_verified": verified,
        "turns_skipped": skipped,
        "errors": errors,
    }
