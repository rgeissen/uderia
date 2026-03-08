#!/usr/bin/env python3
"""
Sync global parameters from tda_config.json to database.
This is a one-time bootstrap operation.

Usage:
    python maintenance/sync_global_parameters.py
"""

import sys
import json
import sqlite3
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from trusted_data_agent.core.config_manager import ConfigManager

def sync_global_parameters():
    """Sync global_parameters from tda_config.json to database."""
    
    # Load from tda_config.json
    config_mgr = ConfigManager()
    bootstrap_config = config_mgr._load_bootstrap_template()
    global_params = bootstrap_config.get('global_parameters', {})
    
    if not global_params:
        print("❌ No global_parameters found in tda_config.json")
        return
    
    # Connect to database
    db_path = project_root / 'tda_auth.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Sync each parameter
    synced = 0
    for param_name, param_value in global_params.items():
        # Check if parameter exists
        cursor.execute(
            "SELECT default_value FROM global_parameters WHERE parameter_name = ?",
            (param_name,)
        )
        row = cursor.fetchone()
        
        if row:
            # Update existing
            cursor.execute(
                "UPDATE global_parameters SET default_value = ?, updated_at = CURRENT_TIMESTAMP WHERE parameter_name = ?",
                (str(param_value), param_name)
            )
            print(f"✅ Updated: {param_name} = {param_value}")
        else:
            # Insert new
            cursor.execute(
                """INSERT INTO global_parameters 
                   (parameter_name, display_name, parameter_type, description, default_value, is_system_managed, is_user_configurable)
                   VALUES (?, ?, 'string', 'Synced from tda_config.json', ?, 0, 1)""",
                (param_name, param_name.replace('_', ' ').title(), str(param_value))
            )
            print(f"✅ Created: {param_name} = {param_value}")
        
        synced += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n🎉 Synced {synced} global parameter(s) from tda_config.json to database")
    print("💡 Application will now read from database at runtime")

if __name__ == "__main__":
    sync_global_parameters()
