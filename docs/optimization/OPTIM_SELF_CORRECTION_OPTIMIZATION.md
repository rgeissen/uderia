# Optimization Ticket: @OPTIM Self-Correction Loop Efficiency

## Status
🎯 **Priority**: HIGH
📅 **Created**: 2026-02-09
🔍 **Category**: Deterministic Code Optimization

## Problem Statement

Performance testing revealed that @OPTIM's self-correction loop wastes 95%+ of tokens on blind retries when schema validation fails.

**Evidence:**
- Test query: "what is the system utilization for the past 24 hours"
- Profile: @OPTIM (without RAG)
- Result: 166,690 input tokens, 4,196 output tokens, 36.48s
- Root cause: TDA_FinalReport failed schema validation 3 times
- Each retry re-sent full 170KB context (53K tokens × 3 retries = 159K wasted)

**Current Behavior:**
```
Attempt 1: LLM returns key_observations as strings → Validation fails
Attempt 2: Full context resent (170KB) → Same error
Attempt 3: Full context resent (170KB) → Same error
Result: 159,000 tokens wasted with no learning
```

## Optimization Opportunities

### 1. Improve Schema Communication (LOW EFFORT, HIGH IMPACT)

**Current Issue:** Tool schemas don't include examples, LLM guesses format

**Fix:**
- Add examples to TDA_FinalReport schema showing Observation object structure
- Include sample valid responses in tool description
- Add schema validation error messages that show correct format

**Expected Impact:** 70-80% reduction in schema validation failures

**Files to Update:**
- `src/trusted_data_agent/mcp_adapter/tda_tools.py` - Add examples to schema
- `src/trusted_data_agent/agent/formatter.py` - Improve error messages

**Implementation:**
```python
# Before
"key_observations": {
    "type": "array",
    "items": {"$ref": "#/definitions/Observation"}
}

# After
"key_observations": {
    "type": "array",
    "items": {"$ref": "#/definitions/Observation"},
    "examples": [[
        {"observation": "High CPU usage detected", "insight": "Potential bottleneck"},
        {"observation": "Memory stable at 45%", "insight": "No memory pressure"}
    ]]
}
```

### 2. Context Compression for Retries (MEDIUM EFFORT, HIGH IMPACT)

**Current Issue:** Each retry sends full 170KB context

**Fix:**
- Compress context for retries: keep only last 2 turns + error message
- Remove tool outputs > 5KB (keep summaries)
- Reduce from 170KB → <50KB (70% reduction)

**Expected Impact:** 70% token reduction per retry

**Files to Update:**
- `src/trusted_data_agent/agent/phase_executor.py` - Add context compression for corrections

**Implementation:**
```python
async def _generate_correction_with_compressed_context(
    self, failed_action, error_result, full_context
):
    # Compress context for retry
    compressed = {
        "last_2_turns": full_context[-2:],
        "error": error_result,
        "schema": failed_action.get("schema"),
        "examples": failed_action.get("examples")  # NEW: Include examples
    }

    correction = await correction_strategy.generate_correction(
        failed_action, error_result, compressed
    )
    return correction
```

### 3. Adaptive Learning (MEDIUM EFFORT, MEDIUM IMPACT)

**Current Issue:** Same prompt used for all retries, LLM repeats error

**Fix:**
- Track correction attempts in state
- On 2nd+ retry, inject previous failed response as anti-example
- "You previously returned X which failed validation. DO NOT repeat this pattern."

**Expected Impact:** 50% reduction in multi-retry scenarios

**Files to Update:**
- `src/trusted_data_agent/agent/phase_executor.py` - Track retry state
- `src/trusted_data_agent/agent/planner.py` - Inject anti-examples

### 4. Intelligent Retry Limits (LOW EFFORT, MEDIUM IMPACT)

**Current Issue:** Fixed 3 retries regardless of error type

**Fix:**
- Stop early if same validation error repeats
- Different limits for different error types (schema: 2, table not found: 3)
- Fallback to user prompt: "Schema validation failed after 2 attempts. Please rephrase."

**Expected Impact:** Prevents worst-case token waste

**Files to Update:**
- `src/trusted_data_agent/agent/phase_executor.py` - Add early stopping logic

## Metrics & Validation

**Before Optimization:**
- Self-correction overhead: 95.4%
- Average retries: 3
- Tokens per retry: 53,000
- Success rate: Low (same error repeats)

**After Optimization (Target):**
- Self-correction overhead: <20%
- Average retries: 1-2
- Tokens per retry: 15,000 (with compression)
- Success rate: 80%+ (examples guide LLM)

**Test Plan:**
1. Run `profile_performance_test.py` with query that previously failed
2. Verify self-correction count reduced
3. Check correction_overhead_percentage in report
4. Validate retry_attempts show compressed context

## Implementation Priority

1. **Week 1**: Schema examples (Opportunity #1) - Quick win
2. **Week 2**: Context compression (Opportunity #2) - High impact
3. **Week 3**: Adaptive learning (Opportunity #3) - Medium complexity
4. **Week 4**: Intelligent limits (Opportunity #4) - Safety net

## Related Files

**Testing Framework:**
- `test/performance/lib/metrics_extractor.py` - Tracks correction metrics
- `test/performance/lib/comparator.py` - Reports overhead percentage

**Core Logic:**
- `src/trusted_data_agent/agent/phase_executor.py` - Self-correction loop
- `src/trusted_data_agent/mcp_adapter/tda_tools.py` - Tool schemas

## References

- Performance test results: `test/performance/results/test_run_20260209_192053.json`
- Comparison report: `test/performance/results/comparison_20260209_192053.md`
- User feedback: "this is very important!" (deterministic code tuning)
- Framework skill: `.claude/skills/profile-perf/profile-perf.md`
