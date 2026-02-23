#!/usr/bin/env python3
"""
Test backward compatibility of prompts.py

This verifies that existing code can still import prompts using the old interface.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_backward_compatibility():
    """Test that all old imports still work"""
    print("=" * 70)
    print("Test: Backward Compatibility")
    print("=" * 70)
    
    try:
        # Import the old way
        from trusted_data_agent.agent.prompts import (
            MASTER_SYSTEM_PROMPT,
            GOOGLE_MASTER_SYSTEM_PROMPT,
            OLLAMA_MASTER_SYSTEM_PROMPT,
            PROVIDER_SYSTEM_PROMPTS,
            ERROR_RECOVERY_PROMPT,
            TACTICAL_SELF_CORRECTION_PROMPT,
            TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR,
            TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR,
            TASK_CLASSIFICATION_PROMPT,
            WORKFLOW_META_PLANNING_PROMPT,
            WORKFLOW_TACTICAL_PROMPT,
            SQL_CONSOLIDATION_PROMPT,
            prompt_loader
        )
        
        print("✓ All imports successful\n")
        
        # Verify content
        prompts_to_check = {
            "MASTER_SYSTEM_PROMPT": MASTER_SYSTEM_PROMPT,
            "GOOGLE_MASTER_SYSTEM_PROMPT": GOOGLE_MASTER_SYSTEM_PROMPT,
            "OLLAMA_MASTER_SYSTEM_PROMPT": OLLAMA_MASTER_SYSTEM_PROMPT,
            "ERROR_RECOVERY_PROMPT": ERROR_RECOVERY_PROMPT,
            "TACTICAL_SELF_CORRECTION_PROMPT": TACTICAL_SELF_CORRECTION_PROMPT,
            "TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR": TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR,
            "TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR": TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR,
            "TASK_CLASSIFICATION_PROMPT": TASK_CLASSIFICATION_PROMPT,
            "WORKFLOW_META_PLANNING_PROMPT": WORKFLOW_META_PLANNING_PROMPT,
            "WORKFLOW_TACTICAL_PROMPT": WORKFLOW_TACTICAL_PROMPT,
            "SQL_CONSOLIDATION_PROMPT": SQL_CONSOLIDATION_PROMPT,
        }
        
        print("Prompt Content Verification:")
        all_valid = True
        for name, content in prompts_to_check.items():
            if content and len(content) > 0:
                print(f"  ✓ {name}: {len(content)} characters")
            else:
                print(f"  ✗ {name}: EMPTY!")
                all_valid = False
        
        print(f"\n✓ PROVIDER_SYSTEM_PROMPTS: {len(PROVIDER_SYSTEM_PROMPTS)} providers")
        print(f"  Providers: {', '.join(PROVIDER_SYSTEM_PROMPTS.keys())}")
        
        print(f"\n✓ prompt_loader exposed: {prompt_loader}")
        
        if all_valid:
            print("\n✓ All prompts loaded successfully with content")
            return True
        else:
            print("\n✗ Some prompts are empty")
            return False
            
    except Exception as e:
        print(f"✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_integration_usage():
    """Test how existing code would use prompts"""
    print("\n" + "=" * 70)
    print("Test: Integration Usage Pattern")
    print("=" * 70)
    
    try:
        from trusted_data_agent.agent.prompts import (
            WORKFLOW_META_PLANNING_PROMPT,
            TASK_CLASSIFICATION_PROMPT
        )
        
        # Simulate how planner.py uses prompts
        print("\nSimulating planner.py usage:")
        print(f"  TASK_CLASSIFICATION_PROMPT length: {len(TASK_CLASSIFICATION_PROMPT)}")
        print(f"  WORKFLOW_META_PLANNING_PROMPT length: {len(WORKFLOW_META_PLANNING_PROMPT)}")
        
        # Show first 100 chars
        print(f"\n  TASK_CLASSIFICATION preview:")
        print(f"    {TASK_CLASSIFICATION_PROMPT[:100]}...")
        
        return True
    except Exception as e:
        print(f"✗ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("Backward Compatibility Test Suite")
    print("=" * 70 + "\n")
    
    tests = [
        test_backward_compatibility,
        test_integration_usage
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
        print("✓ Backward compatibility maintained!")
        return 0
    else:
        print(f"✗ {total - passed} test(s) failed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
