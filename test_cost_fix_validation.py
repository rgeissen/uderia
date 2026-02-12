#!/usr/bin/env python3
"""
Validation script for cost calculation fix.
Tests that costs are calculated correctly and aggregate events are skipped.
"""

import json
import sys
from pathlib import Path

def validate_session_costs(session_file_path):
    """
    Validates that session costs are calculated correctly.

    Args:
        session_file_path: Path to the session JSON file

    Returns:
        dict with validation results
    """
    with open(session_file_path) as f:
        data = json.load(f)

    session_id = data['id']
    turn_data = data['last_turn_data']['workflow_history'][0]
    profile_type = turn_data.get('profile_type', 'N/A')

    print(f'\n{"="*70}')
    print(f'SESSION VALIDATION: {session_id}')
    print(f'Profile Type: {profile_type}')
    print(f'{"="*70}\n')

    # Aggregate event types to skip
    aggregate_types = [
        'conversation_llm_complete',
        'conversation_agent_complete',
        'genie_coordinator_complete',
        'knowledge_retrieval_complete'
    ]

    # Collect costs from all events
    individual_costs = []
    aggregate_costs = []
    all_events = []

    # Check conversation_agent_events
    if 'conversation_agent_events' in turn_data:
        for event in turn_data['conversation_agent_events']:
            event_type = event['type']
            payload = event.get('payload', {})
            cost = payload.get('cost_usd', 0)

            if cost > 0:
                event_info = {
                    'type': event_type,
                    'cost': cost,
                    'input': payload.get('input_tokens', 0),
                    'output': payload.get('output_tokens', 0)
                }
                all_events.append(event_info)

                if event_type in aggregate_types:
                    aggregate_costs.append(event_info)
                else:
                    individual_costs.append(event_info)

    # Check system_events
    if 'system_events' in turn_data:
        for event in turn_data['system_events']:
            event_type = event['type']
            payload = event.get('payload', {})
            details = payload.get('details', {})

            cost = details.get('cost_usd', payload.get('cost_usd', 0))
            input_tokens = details.get('input_tokens', payload.get('input_tokens', 0))
            output_tokens = details.get('output_tokens', payload.get('output_tokens', 0))

            if cost > 0:
                event_info = {
                    'type': event_type,
                    'cost': cost,
                    'input': input_tokens,
                    'output': output_tokens
                }
                all_events.append(event_info)
                individual_costs.append(event_info)

    # Check genie_events
    if 'genie_events' in turn_data and turn_data['genie_events']:
        for event in turn_data['genie_events']:
            event_type = event['type']
            payload = event.get('payload', {})
            cost = payload.get('cost_usd', 0)

            if cost > 0:
                event_info = {
                    'type': event_type,
                    'cost': cost,
                    'input': payload.get('input_tokens', 0),
                    'output': payload.get('output_tokens', 0)
                }
                all_events.append(event_info)

                if event_type in aggregate_types:
                    aggregate_costs.append(event_info)
                else:
                    individual_costs.append(event_info)

    # Calculate totals
    total_all = sum(e['cost'] for e in all_events)
    total_individual = sum(e['cost'] for e in individual_costs)
    total_aggregate = sum(e['cost'] for e in aggregate_costs)

    # Expected cost from tokens
    input_tokens = turn_data['turn_input_tokens']
    output_tokens = turn_data['turn_output_tokens']
    expected_cost = (input_tokens * 0.3 + output_tokens * 1.2) / 1_000_000

    # Print breakdown
    print('📊 INDIVIDUAL EVENTS (Should be counted):')
    for i, evt in enumerate(individual_costs, 1):
        print(f"  {i}. {evt['type']}")
        print(f"     Tokens: {evt['input']:,} in / {evt['output']:,} out")
        print(f"     Cost: ${evt['cost']:.6f}")

    if aggregate_costs:
        print('\n🚫 AGGREGATE EVENTS (Should be skipped):')
        for i, evt in enumerate(aggregate_costs, 1):
            print(f"  {i}. {evt['type']}")
            print(f"     Tokens: {evt['input']:,} in / {evt['output']:,} out")
            print(f"     Cost: ${evt['cost']:.6f} (DUPLICATE/SUM)")

    print(f'\n📈 TOTALS:')
    print(f'  Individual events:     ${total_individual:.6f} (CORRECT)')
    print(f'  Aggregate events:      ${total_aggregate:.6f} (SKIP THESE)')
    print(f'  All events (old way):  ${total_all:.6f} (WRONG)')
    print(f'  Expected from tokens:  ${expected_cost:.6f}')

    # Validation
    print(f'\n✅ VALIDATION RESULTS:')
    individual_matches = abs(total_individual - expected_cost) < 0.000001

    if individual_matches:
        print(f'  ✓ Individual sum matches expected: ${total_individual:.6f}')
    else:
        print(f'  ✗ Individual sum MISMATCH: ${total_individual:.6f} vs ${expected_cost:.6f}')

    if aggregate_costs:
        multiplier = total_all / total_individual if total_individual > 0 else 0
        print(f'  ✓ Found {len(aggregate_costs)} aggregate events to skip')
        print(f'  ✓ Old way would overcount by {multiplier:.2f}×')

    return {
        'session_id': session_id,
        'profile_type': profile_type,
        'individual_cost': total_individual,
        'aggregate_cost': total_aggregate,
        'all_cost': total_all,
        'expected_cost': expected_cost,
        'passes_validation': individual_matches,
        'num_aggregate_events': len(aggregate_costs)
    }


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python test_cost_fix_validation.py <session_file_path>")
        print("\nExample:")
        print("  python test_cost_fix_validation.py tda_sessions/USER_UUID/SESSION_ID.json")
        sys.exit(1)

    session_file = sys.argv[1]

    if not Path(session_file).exists():
        print(f"Error: Session file not found: {session_file}")
        sys.exit(1)

    result = validate_session_costs(session_file)

    print(f'\n{"="*70}')
    if result['passes_validation']:
        print('✅ VALIDATION PASSED: Costs calculated correctly')
    else:
        print('❌ VALIDATION FAILED: Cost mismatch detected')
    print(f'{"="*70}\n')

    sys.exit(0 if result['passes_validation'] else 1)
