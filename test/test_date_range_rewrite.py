"""
Unit test for the date range rewrite pass guard in planner.py.

Validates that _rewrite_plan_for_date_range_loops():
1. Still converts single-date tools (e.g. date param) to per-day loops (existing behavior)
2. Skips loop conversion for range tools (start_date + end_date), extracting the first date instead
"""
import copy
import sys
import os
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

logging.basicConfig(level=logging.INFO)


class MockExecutor:
    """Minimal mock of PlanExecutor for testing the rewrite pass."""

    def __init__(self, meta_plan):
        self.meta_plan = meta_plan
        self.system_events = []

    def _log_system_event(self, event_data):
        self.system_events.append(event_data)

    def _format_sse_with_depth(self, event_data):
        return f"sse:{event_data}"


def run_rewrite_pass(meta_plan):
    """
    Run _rewrite_plan_for_date_range_loops on a given plan.
    Returns (modified_plan, system_events).
    """
    from trusted_data_agent.agent.planner import Planner

    executor = MockExecutor(copy.deepcopy(meta_plan))
    planner = Planner(executor=executor)

    # The method is a generator — consume all yielded SSE events
    sse_events = list(planner._rewrite_plan_for_date_range_loops())

    return executor.meta_plan, executor.system_events, sse_events


def test_single_date_tool_still_loops():
    """
    Tools with a single 'date' parameter should still be converted to loops.
    This is the existing behavior — must not regress.
    """
    plan = [
        {
            "phase": 1,
            "goal": "Get date range",
            "relevant_tools": ["TDA_DateRange"],
            "type": "tool",
        },
        {
            "phase": 2,
            "goal": "Get resource usage per day",
            "relevant_tools": ["dba_resusageSummary"],
            "type": "tool",
            "arguments": {
                "date": "result_of_phase_1"
            }
        },
    ]

    result_plan, events, sse = run_rewrite_pass(plan)

    phase2 = result_plan[1]
    assert phase2["type"] == "loop", f"Expected type='loop', got '{phase2['type']}'"
    assert phase2["loop_over"] == "result_of_phase_1"
    assert phase2["arguments"]["date"] == {"source": "loop_item", "key": "date"}

    assert len(events) == 1
    assert events[0]["type"] == "workaround"

    print("PASS: Single-date tool correctly converted to loop")


def test_range_tool_skips_loop():
    """
    Tools with both start_date AND end_date should NOT be converted to loops.
    Instead, the start_date argument should be rewritten to extract the first
    date from the TDA_DateRange output.
    """
    plan = [
        {
            "phase": 1,
            "goal": "Get current date",
            "relevant_tools": ["TDA_CurrentDate"],
            "type": "tool",
        },
        {
            "phase": 2,
            "goal": "Get date range for past 30 days",
            "relevant_tools": ["TDA_DateRange"],
            "type": "tool",
        },
        {
            "phase": 3,
            "goal": "Get flow control metrics",
            "relevant_tools": ["dba_flowControl"],
            "type": "tool",
            "arguments": {
                "start_date": "result_of_phase_2",
                "end_date": "result_of_phase_1"
            }
        },
    ]

    result_plan, events, sse = run_rewrite_pass(plan)

    phase3 = result_plan[2]

    # Should NOT be a loop
    assert phase3.get("type") != "loop", f"Range tool should NOT be converted to loop, got type='{phase3.get('type')}'"
    assert "loop_over" not in phase3, "Range tool should NOT have loop_over"

    # start_date should be rewritten to extract first date from TDA_DateRange
    expected_start = {"source": "result_of_phase_2", "key": "date"}
    assert phase3["arguments"]["start_date"] == expected_start, \
        f"Expected start_date={expected_start}, got {phase3['arguments']['start_date']}"

    # end_date should remain unchanged (still references TDA_CurrentDate)
    assert phase3["arguments"]["end_date"] == "result_of_phase_1", \
        f"end_date should remain 'result_of_phase_1', got {phase3['arguments']['end_date']}"

    # Should emit optimization event (not workaround)
    assert len(events) == 1
    assert events[0]["type"] == "optimization", f"Expected type='optimization', got '{events[0]['type']}'"

    print("PASS: Range tool correctly skips loop, extracts first date")


def test_range_tool_from_date_to_date():
    """
    Also works with from_date/to_date naming convention.
    """
    plan = [
        {
            "phase": 1,
            "goal": "Get date range",
            "relevant_tools": ["TDA_DateRange"],
            "type": "tool",
        },
        {
            "phase": 2,
            "goal": "Get metrics",
            "relevant_tools": ["some_tool"],
            "type": "tool",
            "arguments": {
                "from_date": "result_of_phase_1",
                "to_date": "2026-02-17"
            }
        },
    ]

    result_plan, events, sse = run_rewrite_pass(plan)

    phase2 = result_plan[1]
    assert phase2.get("type") != "loop", "from_date/to_date tool should NOT be a loop"
    assert phase2["arguments"]["from_date"] == {"source": "result_of_phase_1", "key": "date"}
    assert phase2["arguments"]["to_date"] == "2026-02-17"  # unchanged

    print("PASS: from_date/to_date naming convention handled correctly")


def test_mixed_plan_range_and_single():
    """
    A plan with BOTH a range tool and a single-date tool.
    The range tool should skip the loop, the single-date tool should still loop.
    """
    plan = [
        {
            "phase": 1,
            "goal": "Get date range",
            "relevant_tools": ["TDA_DateRange"],
            "type": "tool",
        },
        {
            "phase": 2,
            "goal": "Get flow control (range tool)",
            "relevant_tools": ["dba_flowControl"],
            "type": "tool",
            "arguments": {
                "start_date": "result_of_phase_1",
                "end_date": "2026-02-17"
            }
        },
        {
            "phase": 3,
            "goal": "Get another date range",
            "relevant_tools": ["TDA_DateRange"],
            "type": "tool",
        },
        {
            "phase": 4,
            "goal": "Get resource usage per day (single-date tool)",
            "relevant_tools": ["dba_resusageSummary"],
            "type": "tool",
            "arguments": {
                "date": "result_of_phase_3"
            }
        },
    ]

    result_plan, events, sse = run_rewrite_pass(plan)

    # Phase 2: range tool — should NOT be a loop
    phase2 = result_plan[1]
    assert phase2.get("type") != "loop", "Range tool should not loop"
    assert phase2["arguments"]["start_date"] == {"source": "result_of_phase_1", "key": "date"}

    # Phase 4: single-date tool — SHOULD be a loop
    phase4 = result_plan[3]
    assert phase4["type"] == "loop", "Single-date tool should still loop"
    assert phase4["arguments"]["date"] == {"source": "loop_item", "key": "date"}

    # Should have 2 events: 1 optimization + 1 workaround
    assert len(events) == 2
    event_types = [e["type"] for e in events]
    assert "optimization" in event_types, "Should have optimization event for range tool"
    assert "workaround" in event_types, "Should have workaround event for single-date tool"

    print("PASS: Mixed plan handled correctly (range skipped, single-date looped)")


def test_no_date_range_phase_unchanged():
    """
    Plans without TDA_DateRange should pass through unchanged.
    """
    plan = [
        {
            "phase": 1,
            "goal": "List databases",
            "relevant_tools": ["base_databaseList"],
            "type": "tool",
            "arguments": {"scope": "user"}
        },
        {
            "phase": 2,
            "goal": "Get space",
            "relevant_tools": ["dba_databaseSpace"],
            "type": "tool",
            "arguments": {}
        },
    ]

    original = copy.deepcopy(plan)
    result_plan, events, sse = run_rewrite_pass(plan)

    assert result_plan == original, "Plan without TDA_DateRange should be unchanged"
    assert len(events) == 0
    print("PASS: Plan without TDA_DateRange passes through unchanged")


if __name__ == "__main__":
    tests = [
        test_single_date_tool_still_loops,
        test_range_tool_skips_loop,
        test_range_tool_from_date_to_date,
        test_mixed_plan_range_and_single,
        test_no_date_range_phase_unchanged,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed == 0:
        print("All tests passed!")
    else:
        sys.exit(1)
