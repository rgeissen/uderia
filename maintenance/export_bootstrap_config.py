#!/usr/bin/env python3
"""
Export current tda_config.json as new bootstrap configuration.

This script:
1. Reads the current tda_config.json
2. Updates timestamps
3. Preserves ALL configuration including session_primer with enabled states
4. Creates backup of old config
5. Writes new bootstrap configuration

Usage:
    python maintenance/export_bootstrap_config.py
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import shutil

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "tda_auth.db"
CONFIG_PATH = PROJECT_ROOT / "tda_config.json"
BACKUP_PATH = PROJECT_ROOT / "tda_config.json.backup"


def update_consumption_profiles_from_db():
    """Update consumption profiles from database if table exists."""
    if not DB_PATH.exists():
        return None

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT name, description, prompts_per_hour, prompts_per_day,
                   config_changes_per_hour, input_tokens_per_month,
                   output_tokens_per_month, is_active
            FROM consumption_profiles
            ORDER BY id
        """)

        profiles = []
        for row in cursor.fetchall():
            profiles.append({
                "name": row[0],
                "description": row[1],
                "prompts_per_hour": row[2],
                "prompts_per_day": row[3],
                "config_changes_per_hour": row[4],
                "input_tokens_per_month": row[5],
                "output_tokens_per_month": row[6],
                "is_active": bool(row[7])
            })

        return profiles if profiles else None

    except sqlite3.OperationalError:
        # Table doesn't exist
        return None
    finally:
        conn.close()


def main():
    """Export current configuration as new bootstrap."""

    if not CONFIG_PATH.exists():
        print(f"❌ Configuration file not found at {CONFIG_PATH}")
        return 1

    print("📦 Creating new bootstrap configuration from current config...")
    print(f"   Source: {CONFIG_PATH}")

    # Read current configuration
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)

    # Backup existing config
    shutil.copy(CONFIG_PATH, BACKUP_PATH)
    print(f"   ✅ Backed up existing config to {BACKUP_PATH}")

    # Update timestamps
    now = datetime.now(timezone.utc).isoformat()
    config['last_modified'] = now
    print(f"   ✅ Updated timestamp: {now}")

    # Update consumption profiles from database if available
    db_consumption_profiles = update_consumption_profiles_from_db()
    if db_consumption_profiles:
        config['consumption_profiles'] = db_consumption_profiles
        print(f"   ✅ Updated consumption profiles from database ({len(db_consumption_profiles)} profiles)")

    # Write new bootstrap configuration
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

    print("\n✅ Export completed successfully!")
    print(f"\n📊 Configuration Summary:")
    print(f"   - Profiles: {len(config.get('profiles', []))}")
    print(f"   - LLM Configurations: {len(config.get('llm_configurations', []))}")
    print(f"   - MCP Servers: {len(config.get('mcp_servers', []))}")
    print(f"   - Consumption Profiles: {len(config.get('consumption_profiles', []))}")
    print(f"   - RAG Collections: {len(config.get('rag_collections', []))}")

    # Analyze session primers
    profiles = config.get('profiles', [])
    profiles_with_primers = []
    enabled_primers = []
    disabled_primers = []

    for p in profiles:
        if 'session_primer' in p and p['session_primer']:
            profiles_with_primers.append(p)
            if isinstance(p['session_primer'], dict):
                if p['session_primer'].get('enabled', False):
                    enabled_primers.append(p)
                else:
                    disabled_primers.append(p)

    print(f"\n📝 Session Primer Status:")
    print(f"   - Total profiles: {len(profiles)}")
    print(f"   - With session_primer field: {len(profiles_with_primers)}")
    print(f"   - ✅ Enabled: {len(enabled_primers)}")
    print(f"   - ❌ Disabled: {len(disabled_primers)}")

    if profiles_with_primers:
        print(f"\n   Primer Details:")
        for p in profiles_with_primers:
            primer = p['session_primer']
            tag = p.get('tag', 'N/A')
            name = p.get('name', 'N/A')[:40]  # Truncate long names

            if isinstance(primer, dict):
                enabled = primer.get('enabled', False)
                mode = primer.get('mode', 'N/A')
                stmt_count = len(primer.get('statements', []))
                status = "✅ Enabled" if enabled else "❌ Disabled"
                print(f"     - @{tag} ({name})")
                print(f"       Status: {status} | Mode: {mode} | Statements: {stmt_count}")
            else:
                print(f"     - @{tag} ({name}): Legacy string format")

    print(f"\n💾 New bootstrap configuration saved!")
    print(f"   This will be used for new user account initialization.")
    print(f"\n   ℹ️  All session_primer configurations have been preserved")
    print(f"   ℹ️  with their current enabled/disabled states.")

    return 0


if __name__ == "__main__":
    exit(main())
