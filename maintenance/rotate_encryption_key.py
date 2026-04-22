#!/usr/bin/env python3
"""
Rotate the TDA_ENCRYPTION_KEY used to encrypt stored API credentials.

Run this BEFORE setting TDA_ENCRYPTION_KEY in .env for the first time, or
whenever you need to rotate to a new key. The script:

  1. Decrypts all stored credentials with the OLD key (default: the dev fallback)
  2. Re-encrypts them with a newly generated secure key
  3. Writes the new key into .env as TDA_ENCRYPTION_KEY
  4. Prints a confirmation — restart the container afterwards

Usage:
    # Rotate from the default dev key to a new secure key (most common):
    python maintenance/rotate_encryption_key.py

    # Rotate from a previously set key to a new one:
    python maintenance/rotate_encryption_key.py --old-key <current_key>

    # Dry-run: decrypt only, verify all credentials are readable, don't write:
    python maintenance/rotate_encryption_key.py --dry-run

Run from the project root directory.
"""

import argparse
import base64
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "tda_auth.db"
ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_DEV_KEY = "dev-master-key-change-in-production"


def derive_user_key(master_key: str, user_id: str) -> bytes:
    salt = user_id.encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = kdf.derive(master_key.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


def decrypt_with_key(master_key: str, user_id: str, encrypted_str: str):
    key = derive_user_key(master_key, user_id)
    fernet = Fernet(key)
    decrypted_json = fernet.decrypt(encrypted_str.encode("utf-8")).decode("utf-8")
    return json.loads(decrypted_json)


def encrypt_with_key(master_key: str, user_id: str, credentials: dict) -> str:
    key = derive_user_key(master_key, user_id)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(json.dumps(credentials).encode("utf-8"))
    return encrypted.decode("utf-8")


def update_env_key(new_key: str):
    """Write or replace TDA_ENCRYPTION_KEY in .env."""
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text().splitlines(keepends=True)
        found = False
        new_lines = []
        for line in lines:
            if line.startswith("TDA_ENCRYPTION_KEY="):
                new_lines.append(f"TDA_ENCRYPTION_KEY={new_key}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"\nTDA_ENCRYPTION_KEY={new_key}\n")
        ENV_PATH.write_text("".join(new_lines))
    else:
        ENV_PATH.write_text(f"TDA_ENCRYPTION_KEY={new_key}\n")


def main():
    parser = argparse.ArgumentParser(description="Rotate TDA_ENCRYPTION_KEY")
    parser.add_argument(
        "--old-key",
        default=os.environ.get("TDA_ENCRYPTION_KEY", DEFAULT_DEV_KEY),
        help="Current master key (default: TDA_ENCRYPTION_KEY env var or dev fallback)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Decrypt and verify only — do not write anything",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, provider, credentials_encrypted FROM user_credentials")
    rows = cursor.fetchall()

    if not rows:
        print("No stored credentials found — nothing to rotate.")
        conn.close()
        sys.exit(0)

    print(f"Found {len(rows)} credential record(s) to rotate.\n")

    # Phase 1: decrypt all with old key (fail fast before writing anything)
    decrypted_records = []
    for row_id, user_id, provider, encrypted_str in rows:
        try:
            creds = decrypt_with_key(args.old_key, user_id, encrypted_str)
            decrypted_records.append((row_id, user_id, provider, creds))
            print(f"  ✓ Decrypted: {provider} (user {user_id[:8]}...)")
        except InvalidToken:
            print(f"  ✗ FAILED to decrypt: {provider} (user {user_id[:8]}...)")
            print(f"    The old key may be wrong. Check --old-key argument.")
            conn.close()
            sys.exit(1)
        except Exception as e:
            print(f"  ✗ ERROR: {provider} (user {user_id[:8]}...): {e}")
            conn.close()
            sys.exit(1)

    if args.dry_run:
        print(f"\nDry-run complete — all {len(rows)} credential(s) successfully decrypted with the provided key.")
        conn.close()
        return

    # Phase 2: generate new key and re-encrypt
    new_key = secrets.token_urlsafe(32)
    print(f"\nGenerated new key. Re-encrypting {len(rows)} credential(s)...")

    successful = 0
    for row_id, user_id, provider, creds in decrypted_records:
        try:
            new_encrypted = encrypt_with_key(new_key, user_id, creds)
            cursor.execute(
                "UPDATE user_credentials SET credentials_encrypted = ? WHERE id = ?",
                (new_encrypted, row_id),
            )
            successful += 1
            print(f"  ✓ Re-encrypted: {provider} (user {user_id[:8]}...)")
        except Exception as e:
            print(f"  ✗ FAILED to re-encrypt: {provider}: {e}")
            print("  Rolling back — database unchanged.")
            conn.rollback()
            conn.close()
            sys.exit(1)

    conn.commit()
    conn.close()

    # Phase 3: write new key to .env
    update_env_key(new_key)

    print(f"\n✅ Rotation complete: {successful}/{len(rows)} credential(s) re-encrypted.")
    print(f"✅ .env updated with new TDA_ENCRYPTION_KEY.")
    print(f"\nNew key: {new_key}")
    print("\n⚠️  Restart the container for the new key to take effect.")


if __name__ == "__main__":
    main()
