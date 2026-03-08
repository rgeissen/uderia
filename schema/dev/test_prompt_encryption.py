#!/usr/bin/env python3
"""
Test License-Based Prompt Encryption System

Tests:
1. Bootstrap decryption (from default_prompts.dat)
2. Tier key derivation
3. Re-encryption for database storage
4. Decryption with valid PE/Enterprise license
5. Access denial for Standard tier
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trusted_data_agent.agent.prompt_encryption import (
    derive_bootstrap_key,
    derive_tier_key,
    decrypt_prompt,
    encrypt_prompt,
    can_access_prompts,
    can_access_prompts_ui,
    get_placeholder_content
)


def test_bootstrap_decryption():
    """Test decryption of default_prompts.dat"""
    print("\n" + "="*70)
    print("TEST 1: Bootstrap Decryption")
    print("="*70)
    
    try:
        # Load encrypted file
        prompts_file = Path(__file__).parent / "default_prompts.dat"
        with open(prompts_file, 'r') as f:
            encrypted_prompts = json.load(f)
        
        print(f"✓ Loaded {len(encrypted_prompts)} encrypted prompts")
        
        # Derive bootstrap key
        bootstrap_key = derive_bootstrap_key()
        print("✓ Derived bootstrap key from public_key.pem")
        
        # Test decryption
        test_prompt_name = "MASTER_SYSTEM_PROMPT"
        if test_prompt_name in encrypted_prompts:
            encrypted_content = encrypted_prompts[test_prompt_name]
            decrypted_content = decrypt_prompt(encrypted_content, bootstrap_key)
            
            print(f"✓ Successfully decrypted {test_prompt_name}")
            print(f"  Content preview: {decrypted_content[:100]}...")
            return True
        else:
            print(f"✗ Test prompt not found: {test_prompt_name}")
            return False
            
    except Exception as e:
        print(f"✗ Bootstrap decryption failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tier_key_derivation():
    """Test tier-specific key derivation"""
    print("\n" + "="*70)
    print("TEST 2: Tier Key Derivation")
    print("="*70)
    
    try:
        # Test PE tier
        pe_license = {
            'tier': 'Prompt Engineer',
            'signature': 'test_signature_pe_123'
        }
        pe_key = derive_tier_key(pe_license)
        print(f"✓ Derived PE tier key: {pe_key[:20]}...")
        
        # Test Enterprise tier
        ent_license = {
            'tier': 'Enterprise',
            'signature': 'test_signature_ent_456'
        }
        ent_key = derive_tier_key(ent_license)
        print(f"✓ Derived Enterprise tier key: {ent_key[:20]}...")
        
        # Verify different licenses produce different keys
        if pe_key != ent_key:
            print("✓ Different licenses produce different keys")
            return True
        else:
            print("✗ Keys should be different for different licenses")
            return False
            
    except Exception as e:
        print(f"✗ Tier key derivation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_re_encryption():
    """Test re-encryption from bootstrap to tier key"""
    print("\n" + "="*70)
    print("TEST 3: Re-encryption (Bootstrap → Tier)")
    print("="*70)
    
    try:
        # Load and decrypt with bootstrap key
        prompts_file = Path(__file__).parent / "default_prompts.dat"
        with open(prompts_file, 'r') as f:
            encrypted_prompts = json.load(f)
        
        bootstrap_key = derive_bootstrap_key()
        test_prompt = encrypted_prompts["MASTER_SYSTEM_PROMPT"]
        decrypted_content = decrypt_prompt(test_prompt, bootstrap_key)
        
        print("✓ Decrypted with bootstrap key")
        
        # Re-encrypt with tier key
        tier_license = {
            'tier': 'Prompt Engineer',
            'signature': 'bootstrap_encryption_key_v1'
        }
        tier_key = derive_tier_key(tier_license)
        tier_encrypted = encrypt_prompt(decrypted_content, tier_key)
        
        print("✓ Re-encrypted with tier key")
        
        # Verify decryption with tier key
        tier_decrypted = decrypt_prompt(tier_encrypted, tier_key)
        
        if tier_decrypted == decrypted_content:
            print("✓ Content matches after re-encryption")
            return True
        else:
            print("✗ Content mismatch after re-encryption")
            return False
            
    except Exception as e:
        print(f"✗ Re-encryption failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tier_access_control():
    """Test tier-based access control"""
    print("\n" + "="*70)
    print("TEST 4: Tier Access Control")
    print("="*70)

    try:
        # Test runtime access - ALL tiers should have runtime access
        all_tiers = ['Standard', 'Prompt Engineer', 'Enterprise', 'Unknown']
        for tier in all_tiers:
            if can_access_prompts(tier):
                print(f"✓ {tier} tier has runtime access (for LLM usage)")
            else:
                print(f"✗ {tier} tier should have runtime access")
                return False

        # Test UI access - only PE/Enterprise should have UI access
        ui_allowed_tiers = ['Prompt Engineer', 'Enterprise']
        for tier in ui_allowed_tiers:
            if can_access_prompts_ui(tier):
                print(f"✓ {tier} tier has UI access (can view/edit)")
            else:
                print(f"✗ {tier} tier should have UI access")
                return False

        # Test UI denied tiers
        ui_denied_tiers = ['Standard', 'Unknown', 'Free']
        for tier in ui_denied_tiers:
            if not can_access_prompts_ui(tier):
                print(f"✓ {tier} tier denied UI access")
            else:
                print(f"✗ {tier} tier should be denied UI access")
                return False

        # Test placeholder content (still used for error scenarios)
        placeholder = get_placeholder_content('Standard')
        if '[ENCRYPTED CONTENT]' in placeholder:
            print("✓ Placeholder content generated correctly")
            return True
        else:
            print("✗ Placeholder content invalid")
            return False

    except Exception as e:
        print(f"✗ Access control test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_encryption_strength():
    """Test that encrypted content is not easily readable"""
    print("\n" + "="*70)
    print("TEST 5: Encryption Strength")
    print("="*70)
    
    try:
        # Load encrypted prompts
        prompts_file = Path(__file__).parent / "default_prompts.dat"
        with open(prompts_file, 'r') as f:
            encrypted_prompts = json.load(f)
        
        test_prompt = encrypted_prompts["MASTER_SYSTEM_PROMPT"]
        
        # Check that common prompt keywords don't appear in encrypted form
        sensitive_terms = ['system', 'prompt', 'database', 'SQL', 'tool', 'capability']
        
        found_plaintext = False
        for term in sensitive_terms:
            if term.lower() in test_prompt.lower():
                print(f"⚠ Found plaintext term '{term}' in encrypted content")
                found_plaintext = True
        
        if not found_plaintext:
            print("✓ No plaintext keywords found in encrypted content")
            print(f"✓ Encrypted content sample: {test_prompt[:80]}...")
            return True
        else:
            print("✗ Encryption may be weak - plaintext terms visible")
            return False
            
    except Exception as e:
        print(f"✗ Encryption strength test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("License-Based Prompt Encryption Test Suite")
    print("="*70)
    
    tests = [
        ("Bootstrap Decryption", test_bootstrap_decryption),
        ("Tier Key Derivation", test_tier_key_derivation),
        ("Re-encryption", test_re_encryption),
        ("Tier Access Control", test_tier_access_control),
        ("Encryption Strength", test_encryption_strength),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*70)
    print("Test Summary")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print()
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
