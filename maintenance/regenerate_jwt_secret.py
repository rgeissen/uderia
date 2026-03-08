#!/usr/bin/env python3
"""
Regenerate JWT Secret Key

This script generates a new JWT secret key for your Uderia Platform installation.
Run this script after installing the application to ensure your JWT tokens are secure.

WARNING: Running this script will invalidate all existing user sessions.
         All users will need to log in again after regeneration.

Usage:
    python maintenance/regenerate_jwt_secret.py
"""

import secrets
import sys
from pathlib import Path


def regenerate_jwt_secret():
    """Generate and save a new JWT secret key."""
    # Determine the tda_keys directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    key_dir = project_root / 'tda_keys'
    key_file = key_dir / 'jwt_secret.key'
    
    # Confirm action
    print("=" * 70)
    print("JWT Secret Key Regeneration")
    print("=" * 70)
    print()
    
    if key_file.exists():
        print("⚠️  WARNING: A JWT secret key already exists.")
        print("   Regenerating will invalidate all existing user sessions.")
        print("   All users will need to log in again.")
        print()
        response = input("Do you want to continue? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print("\n❌ Regeneration cancelled.")
            return False
    else:
        print("No existing JWT secret key found. Generating new one...")
    
    print()
    
    try:
        # Create directory if it doesn't exist
        key_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate new secret key
        new_key = secrets.token_urlsafe(32)
        
        # Save to file
        with open(key_file, 'w', encoding='utf-8') as f:
            f.write(new_key)
        
        # Set restrictive permissions (owner read/write only)
        key_file.chmod(0o600)
        
        print(f"✅ New JWT secret key generated and saved to: {key_file}")
        print(f"   File permissions set to 600 (owner read/write only)")
        print()
        print("🔒 Security Notes:")
        print("   • Keep this file secure and private")
        print("   • Do not commit this file to public repositories")
        print("   • Back it up in a secure location")
        print("   • Each installation should have its own unique key")
        print()
        print("✨ Done! Restart your application for changes to take effect.")
        return True
        
    except Exception as e:
        print(f"\n❌ Error generating JWT secret key: {e}", file=sys.stderr)
        return False


if __name__ == '__main__':
    success = regenerate_jwt_secret()
    sys.exit(0 if success else 1)
