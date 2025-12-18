#!/usr/bin/env python3
"""
Bootstrap Prompt Encryption Script

Encrypts default system prompts for distribution with the application.
Uses public key-derived encryption to protect intellectual property.

Usage:
    python encrypt_default_prompts.py

Input:
    schema/default_prompts/ - Directory containing prompt files:
        - *.txt files for string prompts
        - *.json files for dict prompts (e.g., CHARTING_INSTRUCTIONS)

Output:
    schema/default_prompts.dat - Encrypted prompts for bootstrap

Security Model:
- Encrypted with key derived from public_key.pem (shipped with app)
- Can be decrypted during bootstrap by any installation
- After bootstrap, prompts are re-encrypted with license-tier keys
- Only PE/Enterprise licenses can decrypt from database
"""

import os
import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from trusted_data_agent.agent.prompt_encryption import (
    derive_bootstrap_key,
    encrypt_prompt
)


def load_prompts_from_directory(prompts_dir: Path) -> dict:
    """Load prompts from individual files in the default_prompts directory.
    
    Args:
        prompts_dir: Path to directory containing prompt files
        
    Returns:
        Dictionary mapping prompt names to their content
    """
    prompts = {}
    
    if not prompts_dir.exists():
        raise FileNotFoundError(f"Prompts directory not found: {prompts_dir}")
    
    # Load all .txt files as string prompts
    for txt_file in sorted(prompts_dir.glob("*.txt")):
        prompt_name = txt_file.stem
        with open(txt_file, 'r', encoding='utf-8') as f:
            prompts[prompt_name] = f.read()
    
    # Load all .json files as dict prompts
    for json_file in sorted(prompts_dir.glob("*.json")):
        prompt_name = json_file.stem
        with open(json_file, 'r', encoding='utf-8') as f:
            prompts[prompt_name] = json.load(f)
    
    return prompts


def main():
    """Encrypt default prompts for distribution."""
    
    print("=" * 70)
    print("Uderia Default Prompts Encryption")
    print("=" * 70)
    print()
    
    # Locate prompts directory
    prompts_dir = Path(__file__).resolve().parents[1] / "default_prompts"
    
    print(f"Loading prompts from: {prompts_dir}")
    try:
        PROMPTS_TO_ENCRYPT = load_prompts_from_directory(prompts_dir)
        print(f"✓ Loaded {len(PROMPTS_TO_ENCRYPT)} prompts")
    except Exception as e:
        print(f"✗ Failed to load prompts: {e}")
        return False
    
    # Get encryption key
    print("Deriving bootstrap encryption key from public_key.pem...")
    try:
        bootstrap_key = derive_bootstrap_key()
        print("✓ Bootstrap key derived successfully")
    except Exception as e:
        print(f"✗ Failed to derive bootstrap key: {e}")
        return False
    
    print()
    print("Encrypting prompts...")
    
    # Encrypt all prompts
    encrypted_prompts = {}
    
    for prompt_name, prompt_content in PROMPTS_TO_ENCRYPT.items():
        # Handle CHARTING_INSTRUCTIONS (dict) specially
        if isinstance(prompt_content, dict):
            # Encrypt each value in the dict
            encrypted_dict = {}
            for key, value in prompt_content.items():
                if isinstance(value, str):
                    encrypted_dict[key] = encrypt_prompt(value, bootstrap_key)
                else:
                    encrypted_dict[key] = value
            encrypted_prompts[prompt_name] = encrypted_dict
        elif isinstance(prompt_content, str):
            encrypted_prompts[prompt_name] = encrypt_prompt(prompt_content, bootstrap_key)
        else:
            print(f"  ⚠ Skipping {prompt_name} - unsupported type: {type(prompt_content)}")
            continue
        
        print(f"  ✓ Encrypted: {prompt_name}")
    
    # Save to file
    output_path = Path(__file__).resolve().parents[1] / "default_prompts.dat"
    
    print()
    print(f"Saving encrypted prompts to {output_path}...")
    
    try:
        # Save as JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(encrypted_prompts, f, indent=2)
        
        print(f"✓ Successfully saved to {output_path}")
        
        # Display file size
        file_size = output_path.stat().st_size
        print(f"  File size: {file_size:,} bytes")
        
    except Exception as e:
        print(f"✗ Failed to save encrypted prompts: {e}")
        return False
    
    print()
    print("=" * 70)
    print("Encryption Complete")
    print("=" * 70)
    print()
    print("Next Steps:")
    print("1. Commit schema/default_prompts.dat to repository")
    print("2. On bootstrap, prompts will be decrypted and re-encrypted with tier keys")
    print("3. Only PE/Enterprise licenses can access prompts from database")
    print()
    
    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠ Encryption cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
