#!/usr/bin/env python3
"""
Update rate limiting default settings.

Changes:
1. Set rate_limit_enabled to 'true' (enabled by default)
2. Add rate_limit_global_override setting set to 'false'

This ensures consumption profiles are enforced by default.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import SystemSettings


def update_rate_limiting_defaults():
    """Update rate limiting default settings."""
    
    print("=" * 60)
    print("UPDATING RATE LIMITING DEFAULT SETTINGS")
    print("=" * 60)
    
    try:
        with get_db_session() as session:
            # 1. Enable rate limiting by default
            enabled_setting = session.query(SystemSettings).filter_by(
                setting_key='rate_limit_enabled'
            ).first()
            
            if enabled_setting:
                old_value = enabled_setting.setting_value
                enabled_setting.setting_value = 'true'
                print(f"\n✓ Updated rate_limit_enabled: {old_value} → true")
            else:
                enabled_setting = SystemSettings(
                    setting_key='rate_limit_enabled',
                    setting_value='true',
                    description='Enable or disable rate limiting system-wide'
                )
                session.add(enabled_setting)
                print("\n✓ Created rate_limit_enabled: true")
            
            # 2. Add global override setting (disabled by default)
            override_setting = session.query(SystemSettings).filter_by(
                setting_key='rate_limit_global_override'
            ).first()
            
            if override_setting:
                print(f"✓ rate_limit_global_override already exists: {override_setting.setting_value}")
            else:
                override_setting = SystemSettings(
                    setting_key='rate_limit_global_override',
                    setting_value='false',
                    description='Override all consumption profiles with global limits'
                )
                session.add(override_setting)
                print("✓ Created rate_limit_global_override: false")
            
            session.commit()
            
            print("\n" + "=" * 60)
            print("MIGRATION COMPLETE")
            print("=" * 60)
            print("\nChanges:")
            print("  • Rate limiting is now ENABLED by default")
            print("  • Consumption profiles will be enforced")
            print("  • Global override available for emergency use")
            print("\nNote: Refresh the Admin Panel to see updated settings")
            
            return True
            
    except Exception as e:
        print(f"\n✗ Error updating settings: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = update_rate_limiting_defaults()
    sys.exit(0 if success else 1)
