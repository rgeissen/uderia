#!/usr/bin/env python3
"""
Provenance Key Rotation Utility
================================

Generates a new Ed25519 provenance signing key pair. Old chains remain verifiable
because each chain stores the key_fingerprint used at signing time. Auditors can
load the correct public key by matching fingerprints.

Usage:
    python maintenance/rotate_provenance_key.py

The old key files are backed up with a timestamp suffix before replacement.
"""

import os
import sys
import hashlib
from datetime import datetime

# Ensure project root is on the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "src"))


def rotate_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    keys_dir = os.path.join(project_root, "tda_keys")
    os.makedirs(keys_dir, exist_ok=True)

    priv_path = os.path.join(keys_dir, "provenance_key.pem")
    pub_path = os.path.join(keys_dir, "provenance_key.pub")

    # Backup existing keys
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for path in [priv_path, pub_path]:
        if os.path.exists(path):
            backup = f"{path}.{timestamp}.bak"
            os.rename(path, backup)
            print(f"Backed up: {path} -> {backup}")

    # Generate new key pair
    private_key = Ed25519PrivateKey.generate()

    # Save private key
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    with open(priv_path, 'wb') as f:
        f.write(priv_pem)
    os.chmod(priv_path, 0o600)

    # Save public key
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    with open(pub_path, 'wb') as f:
        f.write(pub_pem)

    # Compute fingerprint
    pub_raw = private_key.public_key().public_bytes_raw()
    fingerprint = hashlib.sha256(pub_raw).hexdigest()

    print(f"\nNew provenance key generated:")
    print(f"  Private key: {priv_path}")
    print(f"  Public key:  {pub_path}")
    print(f"  Fingerprint: {fingerprint}")
    print(f"\nOld chains remain verifiable via stored key_fingerprint in provenance_meta.")
    print(f"Restart the application to load the new key.")


if __name__ == "__main__":
    rotate_key()
