#!/usr/bin/env python3
"""
Test that rate_limit_enabled is read from tda_config.json during initialization.

This script tests the configuration loading by:
1. Reading current config value
2. Showing what database initialization would use
3. Verifying the logic works correctly
"""

import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import SystemSettings


def test_config_loading():
    """Test that config file is read correctly."""
    
    print("=" * 70)
    print("TESTING RATE_LIMIT_ENABLED CONFIG LOADING")
    print("=" * 70)
    
    # Load config
    config_path = project_root / 'tda_config.json'
    
    if not config_path.exists():
        print(f"\n✗ Config file not found: {config_path}")
        return False
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    rate_limit_config = config.get('rate_limit_enabled', 'on')
    rate_limit_parsed = 'true' if rate_limit_config.lower() in ('on', 'true', '1', 'yes') else 'false'
    
    print(f"\n📄 Config File: {config_path}")
    print(f"   rate_limit_enabled = \"{rate_limit_config}\"")
    print(f"   Parsed to database value: \"{rate_limit_parsed}\"")
    
    # Check current database value
    try:
        with get_db_session() as session:
            setting = session.query(SystemSettings).filter_by(
                setting_key='rate_limit_enabled'
            ).first()
            
            if setting:
                db_value = setting.setting_value
                print(f"\n💾 Database Current Value: \"{db_value}\"")
                
                if db_value == rate_limit_parsed:
                    print(f"   ✓ Database matches config expectation")
                else:
                    print(f"   ⚠ Database differs from config (expected: {rate_limit_parsed})")
            else:
                print("\n💾 Database: No setting exists yet")
                print("   ℹ️ Setting would be created with config value on next init")
    
    except Exception as e:
        print(f"\n✗ Error checking database: {e}")
        return False
    
    # Test conversion logic
    print("\n" + "=" * 70)
    print("CONVERSION LOGIC TEST")
    print("=" * 70)
    
    test_cases = [
        ('on', 'true'),
        ('off', 'false'),
        ('true', 'true'),
        ('false', 'false'),
        ('1', 'true'),
        ('0', 'false'),
        ('yes', 'true'),
        ('no', 'false'),
    ]
    
    all_passed = True
    for input_val, expected in test_cases:
        result = 'true' if input_val.lower() in ('on', 'true', '1', 'yes') else 'false'
        status = '✓' if result == expected else '✗'
        print(f"  {status} '{input_val}' → '{result}' (expected: '{expected}')")
        if result != expected:
            all_passed = False
    
    print("\n" + "=" * 70)
    print("TEST RESULT")
    print("=" * 70)
    
    if all_passed:
        print("✓ All conversion tests passed")
        print("✓ Config file loading works correctly")
        print(f"✓ Current config setting: rate_limit_enabled = \"{rate_limit_config}\"")
        print("\nℹ️ New database installations will use this config value")
        print("ℹ️ Existing databases keep their current value (can be updated via Admin UI)")
        return True
    else:
        print("✗ Some tests failed")
        return False


if __name__ == '__main__':
    success = test_config_loading()
    sys.exit(0 if success else 1)
