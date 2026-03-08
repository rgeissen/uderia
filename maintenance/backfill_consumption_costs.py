#!/usr/bin/env python3
"""
Backfill consumption costs for existing sessions.

This script recalculates costs for all existing sessions and updates
the user_consumption table with accurate cost data.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import UserConsumption, ConsumptionTurn
from trusted_data_agent.core.cost_manager import get_cost_manager

def backfill_costs():
    """Backfill costs for all existing sessions."""

    # Get sessions directory
    sessions_dir = Path('tda_sessions')
    if not sessions_dir.exists():
        print(f"Sessions directory not found: {sessions_dir}")
        return

    cost_manager = get_cost_manager()

    # Track statistics
    users_updated = set()
    total_cost_cents = 0
    total_turns = 0

    print("Scanning sessions...")

    # Scan all user directories
    for user_dir in sessions_dir.iterdir():
        if not user_dir.is_dir():
            continue

        user_uuid = user_dir.name
        print(f"\nProcessing user: {user_uuid}")

        user_total_cost_usd = 0.0  # Accumulate in USD, convert to cents at the end
        user_turns = 0

        # Scan all session files
        for session_file in user_dir.glob('*.json'):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)

                session_id = session_file.stem
                workflow_history = session_data.get('last_turn_data', {}).get('workflow_history', [])

                for turn_idx, turn in enumerate(workflow_history, 1):
                    if not turn.get('isValid', True):
                        continue

                    provider = turn.get('provider', 'Unknown')
                    model = turn.get('model', 'unknown')
                    input_tokens = turn.get('turn_input_tokens', 0)
                    output_tokens = turn.get('turn_output_tokens', 0)

                    # Calculate cost
                    cost_usd = cost_manager.calculate_cost(provider, model, input_tokens, output_tokens)

                    user_total_cost_usd += cost_usd
                    user_turns += 1

                    print(f"  Session {session_id[:8]}, Turn {turn_idx}: {provider}/{model} = ${cost_usd:.4f}")

            except Exception as e:
                print(f"  Error processing {session_file.name}: {e}")
                continue

        if user_turns > 0:
            # Convert total cost to micro-dollars
            user_total_cost_cents = int(user_total_cost_usd * 1000000)

            users_updated.add(user_uuid)
            total_cost_cents += user_total_cost_cents
            total_turns += user_turns

            # Update user consumption record
            try:
                with get_db_session() as db:
                    consumption = db.query(UserConsumption).filter_by(user_id=user_uuid).first()

                    if consumption:
                        old_cost = consumption.estimated_cost_usd
                        consumption.estimated_cost_usd = user_total_cost_cents
                        db.commit()
                        print(f"  Updated user consumption: ${old_cost/1000000:.6f} -> ${user_total_cost_cents/1000000:.6f} (from ${user_total_cost_usd:.6f})")
                    else:
                        print(f"  Warning: No consumption record found for user {user_uuid}")

            except Exception as e:
                print(f"  Error updating consumption for user {user_uuid}: {e}")

    print("\n" + "="*60)
    print(f"Backfill complete!")
    print(f"  Users updated: {len(users_updated)}")
    print(f"  Total turns processed: {total_turns}")
    print(f"  Total cost: ${total_cost_cents/1000000:.6f}")
    print("="*60)

if __name__ == '__main__':
    print("Starting consumption cost backfill...")
    print("This will recalculate costs for all existing sessions.\n")

    backfill_costs()

    print("\nBackfill completed successfully!")
