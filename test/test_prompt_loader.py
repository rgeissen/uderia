#!/usr/bin/env python3
"""
Test script for PromptLoader

Tests basic functionality of the new database-backed prompt system.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trusted_data_agent.agent.prompt_loader import get_prompt_loader

def test_loader_initialization():
    """Test that loader initializes with license validation"""
    print("=" * 70)
    print("Test 1: PromptLoader Initialization")
    print("=" * 70)
    
    try:
        loader = get_prompt_loader()
        print(f"✓ Loader initialized successfully")
        print(f"  License Tier: {loader._tier}")
        print(f"  Database Path: {loader.db_path}")
        return True
    except Exception as e:
        print(f"✗ Initialization failed: {e}")
        return False

def test_list_prompts():
    """Test listing all prompts"""
    print("\n" + "=" * 70)
    print("Test 2: List All Prompts")
    print("=" * 70)
    
    try:
        loader = get_prompt_loader()
        prompts = loader.list_prompts()
        
        print(f"✓ Found {len(prompts)} prompts:\n")
        
        # Group by category
        by_category = {}
        for p in prompts:
            cat = p.get('category') or 'Uncategorized'
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(p)
        
        for category, items in sorted(by_category.items()):
            print(f"  {category}:")
            for p in items:
                print(f"    - {p['name']} ({p['display_name']})")
        
        return True
    except Exception as e:
        print(f"✗ List prompts failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_load_prompt():
    """Test loading a specific prompt"""
    print("\n" + "=" * 70)
    print("Test 3: Load Specific Prompt")
    print("=" * 70)
    
    try:
        loader = get_prompt_loader()
        
        # Test loading MASTER_SYSTEM_PROMPT
        prompt_name = 'MASTER_SYSTEM_PROMPT'
        content = loader.get_prompt(prompt_name)
        
        print(f"✓ Loaded {prompt_name}")
        print(f"  Content length: {len(content)} characters")
        print(f"  First 100 chars: {content[:100]}...")
        
        return True
    except Exception as e:
        print(f"✗ Load prompt failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_load_with_parameters():
    """Test parameter resolution"""
    print("\n" + "=" * 70)
    print("Test 4: Parameter Resolution")
    print("=" * 70)
    
    try:
        loader = get_prompt_loader()
        
        # Load TASK_CLASSIFICATION_PROMPT with parameters
        prompt_name = 'TASK_CLASSIFICATION_PROMPT'
        content = loader.get_prompt(
            prompt_name,
            parameters={'task_description': 'Test task'}
        )
        
        print(f"✓ Loaded {prompt_name} with parameters")
        print(f"  Content length: {len(content)} characters")
        
        if 'Test task' in content:
            print(f"  ✓ Parameter substitution successful")
        else:
            print(f"  ⚠ Parameter may not have been substituted")
        
        return True
    except Exception as e:
        print(f"✗ Parameter resolution failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_prompt_metadata():
    """Test getting prompt metadata"""
    print("\n" + "=" * 70)
    print("Test 5: Prompt Metadata")
    print("=" * 70)
    
    try:
        loader = get_prompt_loader()
        
        prompt_name = 'WORKFLOW_META_PLANNING_PROMPT'
        metadata = loader.get_prompt_metadata(prompt_name)
        
        if metadata:
            print(f"✓ Retrieved metadata for {prompt_name}:")
            print(f"  Display Name: {metadata['display_name']}")
            print(f"  Description: {metadata['description']}")
            print(f"  Role: {metadata['role']}")
            print(f"  Category: {metadata.get('category', 'N/A')}")
            print(f"  Version: {metadata['version']}")
            return True
        else:
            print(f"✗ No metadata found for {prompt_name}")
            return False
            
    except Exception as e:
        print(f"✗ Get metadata failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_tier_access():
    """Test tier access checking"""
    print("\n" + "=" * 70)
    print("Test 6: Tier Access Check")
    print("=" * 70)
    
    try:
        loader = get_prompt_loader()
        
        print(f"  Current tier: {loader._tier}")
        print(f"  Has Standard access: {loader.has_tier_access('Standard')}")
        print(f"  Has Prompt Engineer access: {loader.has_tier_access('Prompt Engineer')}")
        print(f"  Has Enterprise access: {loader.has_tier_access('Enterprise')}")
        
        return True
    except Exception as e:
        print(f"✗ Tier access check failed: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("PromptLoader Test Suite")
    print("=" * 70 + "\n")
    
    tests = [
        test_loader_initialization,
        test_list_prompts,
        test_load_prompt,
        test_load_with_parameters,
        test_prompt_metadata,
        test_tier_access
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("✓ All tests passed!")
        return 0
    else:
        print(f"✗ {total - passed} test(s) failed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
