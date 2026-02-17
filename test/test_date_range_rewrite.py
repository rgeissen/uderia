"""
Unit test for the date range rewrite pass guard in planner.py.

Validates that _rewrite_plan_for_date_range_loops():
1. Converts single-date tools (e.g. date param) to per-day loops
2. Wires both start_date + end_date from TDA_DateRange for range tools
3. Unwraps LLM-generated loops when the tool is actually a range tool
"""
import copy
import sys
import os
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

logging.basicConfig(level=logging.INFO)


class MockToolSpec:
    """Minimal mock of an MCP tool spec."""
    def __init__(self, name, args):
        self.name = name
        self.args = args
        self.description = f"Mock tool {name}"


# Mock MCP tool registry — range tools have start_date + end_date, single-date tools have date
MOCK_MCP_TOOLS = {
    "dba_flowControl": MockToolSpec("dba_flowControl", {
        "start_date": {"type": "string", "required": True, "description": "Start date"},
        "end_date": {"type": "string", "required": True, "description": "End date"},
    }),
    "dba_resusageSummary": MockToolSpec("dba_resusageSummary", {
        "date": {"type": "string", "required": True, "description": "Date"},
    }),
    "some_tool": MockToolSpec("some_tool", {
        "from_date": {"type": "string", "required": True, "description": "From date"},
        "to_date": {"type": "string", "required": True, "description": "To date"},
    }),
}


class MockExecutor:
    """Minimal mock of PlanExecutor for testing the rewrite pass."""

    def __init__(self, meta_plan):
        self.meta_plan = meta_plan
        self.system_events = []
        self.dependencies = {
            'STATE': {
                'mcp_tools': MOCK_MCP_TOOLS
            }
        }

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
    Both args should be wired to TDA_DateRange output (start_date and end_date keys).
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

    # start_date should reference TDA_DateRange start_date
    expected_start = {"source": "result_of_phase_2", "key": "start_date"}
    assert phase3["arguments"]["start_date"] == expected_start, \
        f"Expected start_date={expected_start}, got {phase3['arguments']['start_date']}"

    # end_date should ALSO reference TDA_DateRange end_date (not TDA_CurrentDate)
    expected_end = {"source": "result_of_phase_2", "key": "end_date"}
    assert phase3["arguments"]["end_date"] == expected_end, \
        f"Expected end_date={expected_end}, got {phase3['arguments']['end_date']}"

    # Should emit optimization event (not workaround)
    assert len(events) == 1
    assert events[0]["type"] == "optimization", f"Expected type='optimization', got '{events[0]['type']}'"

    print("PASS: Range tool correctly skips loop, wires both start_date and end_date")


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
    assert phase2["arguments"]["from_date"] == {"source": "result_of_phase_1", "key": "start_date"}
    assert phase2["arguments"]["to_date"] == {"source": "result_of_phase_1", "key": "end_date"}

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
    assert phase2["arguments"]["start_date"] == {"source": "result_of_phase_1", "key": "start_date"}
    assert phase2["arguments"]["end_date"] == {"source": "result_of_phase_1", "key": "end_date"}

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


def test_unwrap_llm_loop_for_range_tool():
    """
    When the LLM generates a per-day loop for a range tool (start_date + end_date),
    the rewrite pass should unwrap the loop and wire both args to TDA_DateRange.
    This is the actual LLM output observed in production.
    """
    plan = [
        {
            "phase": 1,
            "goal": "Get the current date.",
            "relevant_tools": ["TDA_CurrentDate"],
            "type": "tool",
            "arguments": {}
        },
        {
            "phase": 2,
            "goal": "Calculate the date range for the last 2 days.",
            "relevant_tools": ["TDA_DateRange"],
            "type": "tool",
            "arguments": {
                "date_phrase": "last 2 days",
                "start_date": "result_of_phase_1"
            }
        },
        {
            "phase": 3,
            "goal": "Show flow control metrics for the date range provided.",
            "relevant_tools": ["dba_flowControl"],
            "type": "loop",
            "loop_over": "result_of_phase_2",
            "arguments": {
                "start_date": {"source": "loop_item", "key": "date"},
                "end_date": {"source": "loop_item", "key": "date"}
            }
        },
        {
            "phase": 4,
            "goal": "Generate the final report.",
            "relevant_tools": ["TDA_FinalReport"],
            "type": "tool",
            "arguments": {}
        }
    ]

    result_plan, events, sse = run_rewrite_pass(plan)

    phase3 = result_plan[2]

    # Loop should be UNWRAPPED — no longer type=loop
    assert phase3.get("type") != "loop", \
        f"Range tool loop should be unwrapped, got type='{phase3.get('type')}'"
    assert "loop_over" not in phase3, \
        "loop_over should be removed after unwrapping"

    # Both args should reference TDA_DateRange output
    expected_start = {"source": "result_of_phase_2", "key": "start_date"}
    expected_end = {"source": "result_of_phase_2", "key": "end_date"}
    assert phase3["arguments"]["start_date"] == expected_start, \
        f"Expected start_date={expected_start}, got {phase3['arguments']['start_date']}"
    assert phase3["arguments"]["end_date"] == expected_end, \
        f"Expected end_date={expected_end}, got {phase3['arguments']['end_date']}"

    # Should emit optimization event
    assert len(events) == 1
    assert events[0]["type"] == "optimization"

    # Other phases should be unchanged
    assert result_plan[0]["relevant_tools"] == ["TDA_CurrentDate"]
    assert result_plan[3]["relevant_tools"] == ["TDA_FinalReport"]

    print("PASS: LLM-generated loop unwrapped for range tool, both args wired correctly")


def test_single_date_tool_loop_left_alone():
    """
    When the LLM correctly generates a loop for a single-date tool,
    it should be left unchanged.
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
            "type": "loop",
            "loop_over": "result_of_phase_1",
            "arguments": {
                "date": {"source": "loop_item", "key": "date"}
            }
        },
    ]

    original = copy.deepcopy(plan)
    result_plan, events, sse = run_rewrite_pass(plan)

    # Should be unchanged — LLM correctly created loop for single-date tool
    assert result_plan[1]["type"] == "loop", "Single-date loop should stay as loop"
    assert result_plan[1]["loop_over"] == "result_of_phase_1"
    assert result_plan[1]["arguments"]["date"] == {"source": "loop_item", "key": "date"}
    assert len(events) == 0, "No events should be emitted for correct loops"

    print("PASS: Single-date tool loop left unchanged")


if __name__ == "__main__":
    tests = [
        test_single_date_tool_still_loops,
        test_range_tool_skips_loop,
        test_range_tool_from_date_to_date,
        test_mixed_plan_range_and_single,
        test_no_date_range_phase_unchanged,
        test_unwrap_llm_loop_for_range_tool,
        test_single_date_tool_loop_left_alone,
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
