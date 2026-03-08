#!/usr/bin/env python3
"""
Quick test to verify PROVIDER_SYSTEM_PROMPTS is loading correctly
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    print("Importing prompts module...")
    from trusted_data_agent.agent.prompts import PROVIDER_SYSTEM_PROMPTS
    
    print("✓ Import successful!\n")
    print(f"PROVIDER_SYSTEM_PROMPTS type: {type(PROVIDER_SYSTEM_PROMPTS)}")
    print(f"Number of providers: {len(PROVIDER_SYSTEM_PROMPTS)}")
    print(f"Providers: {list(PROVIDER_SYSTEM_PROMPTS.keys())}\n")
    
    for provider, prompt in PROVIDER_SYSTEM_PROMPTS.items():
        if prompt:
            print(f"✓ {provider}: {len(prompt)} characters")
        else:
            print(f"✗ {provider}: EMPTY or None!")
    
    print("\nTest passed!")
    
except Exception as e:
    print(f"✗ Failed to import: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
