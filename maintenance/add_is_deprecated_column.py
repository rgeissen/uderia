#!/usr/bin/env python3
"""
Migration script to add is_deprecated column to llm_model_costs table.

This script:
1. Adds the is_deprecated column to existing databases
2. Sets is_deprecated=True for models with DEPRECATED in their notes
3. Safe to run multiple times (checks if column exists first)

Usage:
    python maintenance/add_is_deprecated_column.py
"""

import sys
import sqlite3
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from trusted_data_agent.auth.database import get_db_session
from sqlalchemy import text


def add_is_deprecated_column():
    """Add is_deprecated column to llm_model_costs table if it doesn't exist."""

    print("🔄 Checking if is_deprecated column needs to be added...")

    with get_db_session() as db:
        # Check if column already exists
        result = db.execute(text("PRAGMA table_info(llm_model_costs)")).fetchall()
        columns = [row[1] for row in result]

        if 'is_deprecated' in columns:
            print("✅ Column is_deprecated already exists. No migration needed.")
            return

        print("📝 Adding is_deprecated column to llm_model_costs table...")

        # Add the column (SQLite doesn't support adding NOT NULL with default in ALTER TABLE)
        db.execute(text("""
            ALTER TABLE llm_model_costs
            ADD COLUMN is_deprecated BOOLEAN DEFAULT 0
        """))

        # Create index on is_deprecated
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_llm_costs_deprecated
            ON llm_model_costs(is_deprecated)
        """))

        db.commit()
        print("✅ Column added successfully")

        # Now set is_deprecated=True for models with DEPRECATED in notes
        print("🔍 Scanning for deprecated models in notes...")

        result = db.execute(text("""
            UPDATE llm_model_costs
            SET is_deprecated = 1
            WHERE notes LIKE '%DEPRECATED%'
               OR notes LIKE '%deprecated%'
               OR notes LIKE '%discontinued%'
               OR notes LIKE '%UNVERIFIED%'
        """))

        db.commit()

        deprecated_count = result.rowcount
        print(f"✅ Marked {deprecated_count} models as deprecated based on notes")

        # Show summary
        result = db.execute(text("""
            SELECT provider, model, notes
            FROM llm_model_costs
            WHERE is_deprecated = 1
            ORDER BY provider, model
        """)).fetchall()

        if result:
            print("\n📊 Deprecated models:")
            print("-" * 100)
            for row in result:
                provider, model, notes = row
                notes_preview = notes[:60] + "..." if notes and len(notes) > 60 else notes or ""
                print(f"  {provider:20} {model:50} {notes_preview}")

        print("\n✅ Migration completed successfully!")


if __name__ == '__main__':
    try:
        add_is_deprecated_column()
    except Exception as e:
        print(f"❌ Migration failed: {e}", file=sys.stderr)
        sys.exit(1)
