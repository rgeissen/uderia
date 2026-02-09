# Profile Performance Testing & Optimization Framework

## Overview

This skill provides a comprehensive framework for testing and optimizing Uderia profile execution performance. The primary focus is on **improving @OPTIM (tool_enabled) profiles** by analyzing strategic plans, execution traces, and identifying optimization opportunities.

**Key Objectives:**
- Compare performance between profile types (@IDEAT vs @OPTIM)
- Analyze strategic planning efficiency
- Identify token optimization opportunities
- Detect issues: recursive executions, inappropriate LLM formats, excessive overhead
- Generate actionable optimization reports

---

## Quick Start

### Run Performance Comparison

```bash
# From project root
cd test/performance

# Compare IDEAT vs OPTIM for a query
python3 profile_performance_test.py \
  --query "how many databases are on the system?" \
  --profile1 IDEAT \
  --profile2 OPTIM \
  --timeout 120

# Results saved to:
# - results/test_run_<timestamp>.json (machine-readable)
# - results/comparison_<timestamp>.md (human-readable)
```

### Quick Test via REST API

```bash
# Authenticate
JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r '.token')

# Create session
SESSION=$(curl -s -X POST http://localhost:5050/api/v1/sessions \
  -H "Authorization: Bearer $JWT" | jq -r '.session_id')

# Submit query with profile override
TASK=$(curl -s -X POST http://localhost:5050/api/v1/sessions/$SESSION/query \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "how many databases are on the system?",
    "profile_id": "profile-1764006444002-z0hdduce9"
  }' | jq -r '.task_id')

# Poll for results
curl -s -X GET "http://localhost:5050/api/v1/tasks/$TASK" \
  -H "Authorization: Bearer $JWT" | jq '.'
```

---

## Framework Architecture

### Components

```
test/performance/
├── lib/
│   ├── uderia_client.py       # REST API client (auth, sessions, queries, polling)
│   ├── metrics_extractor.py   # Parse task results & session files for metrics
│   └── comparator.py          # Analyze & generate comparison reports
├── profile_performance_test.py # Main CLI orchestration script
└── results/                   # Output directory (JSON + Markdown reports)
```

### Workflow

1. **Authenticate** → Get JWT token
2. **Find Profiles** → Lookup profile IDs by tag (IDEAT, OPTIM)
3. **Create Sessions** → One session per profile (uses default profile)
4. **Submit Queries** → Override with `profile_id` parameter (proper REST approach)
5. **Poll Tasks** → Wait for completion with timeout
6. **Extract Metrics** → Parse task events + session files
7. **Compare & Report** → Generate optimization insights

---

## Profile Types & Execution Paths

### @IDEAT (llm_only)

**Architecture:** Direct LLM conversation with optional tool calling

**Characteristics:**
- Execution path: `conversation_agent`
- LLM calls: 1-2 per query
- Context overhead: ~500-1K tokens
- Tool integration: Optional via LangChain
- Use case: Chat, simple Q&A, single-step operations

**Execution Flow:**
```
User Query → LLM (with tools context) → Tool Selection → Tool Execution → Response
```

**Metrics to Track:**
- `conversation_llm_step` events (count = LLM calls)
- `conversation_agent_complete` payload (tokens, duration, tools_used)
- Session file: `conversation_agent_events[]` array

---

### @OPTIM (tool_enabled)

**Architecture:** Multi-phase Planner/Executor with strategic + tactical planning

**Characteristics:**
- Execution path: `planner/executor`
- LLM calls: 2-5+ per query (strategic + tactical per phase)
- Context overhead: ~3.5K-8K tokens (first turn)
- Tool integration: Full MCP tools with RAG learning
- Use case: Complex workflows, multi-step operations, database queries

**Execution Flow:**
```
User Query
  ↓
Strategic Planning LLM Call (meta-plan: phases + goals)
  ↓
Phase 1:
  ├→ Tactical Planning LLM Call (tool selection) OR FASTPATH (skip LLM if obvious)
  └→ Tool Execution (via MCP)
  ↓
Phase 2:
  ├→ Tactical Planning LLM Call
  └→ Tool Execution
  ↓
Response Synthesis
```

**Key Optimizations:**
- **FASTPATH**: Skip tactical LLM call when tool selection is obvious (1 relevant tool)
- **Plan Hydration**: Inject previous turn results to skip redundant tool calls
- **RAG Learning**: Retrieve champion cases from ChromaDB to reuse proven strategies
- **Context Distillation**: Summarize large tool outputs (>500 rows) to save tokens

**Metrics to Track:**
- `token_update` events (cumulative: `total_input`, `total_output`)
- `tool_intent` + `tool_result` events (tool selections + executions)
- Session file: `original_plan[]` (strategic plan structure)
- Session file: `execution_trace[]` (step-by-step with TDA_SystemLog events)

---

## Critical Data Structures

### Task Result (from REST API)

**Endpoint:** `GET /api/v1/tasks/{task_id}`

**Key Events:**

**For @IDEAT (llm_only):**
```json
{
  "event_type": "notification",
  "event_data": {
    "type": "conversation_llm_step",
    "payload": {
      "step_number": 1,
      "step_name": "Tool Selection",
      "input_tokens": 542,
      "output_tokens": 89,
      "duration_ms": 2345
    }
  }
}
```

**For @OPTIM (tool_enabled):**
```json
{
  "event_type": "token_update",
  "event_data": {
    "total_input": 10384,    // Cumulative input tokens
    "total_output": 1119     // Cumulative output tokens
  }
}
```

### Session File Structure

**Location:** `tda_sessions/{user_uuid}/{session_id}.json`

**Key Fields:**
```json
{
  "profile_tag": "OPTIM",
  "profile_id": "profile-xxx",
  "provider": "Friendli",
  "model": "MiniMaxAI/MiniMax-M2.1",
  "input_tokens": 10698,
  "output_tokens": 1300,
  "last_turn_data": {
    "workflow_history": [
      {
        "turn": 1,
        "turn_input_tokens": 10698,
        "turn_output_tokens": 1300,
        "duration_ms": 20330,
        "tools_used": ["base_databaseList", "TDA_FinalReport"],

        // STRATEGIC PLAN (tool_enabled only)
        "original_plan": [
          {
            "phase": 1,
            "goal": "Get the list of all databases",
            "relevant_tools": ["base_databaseList"],
            "arguments": {}
          },
          {
            "phase": 2,
            "goal": "Generate the final report",
            "relevant_tools": ["TDA_FinalReport"],
            "arguments": {}
          }
        ],

        // EXECUTION TRACE (step-by-step log)
        "execution_trace": [
          {
            "action": {
              "tool_name": "TDA_SystemLog",
              "arguments": {
                "message": "Calling LLM for Planning",
                "details": {
                  "summary": "Generating strategic meta-plan",
                  "input_tokens": 7376,
                  "output_tokens": 262
                }
              }
            },
            "result": {"status": "info"}
          },
          {
            "action": {
              "tool_name": "TDA_SystemLog",
              "arguments": {
                "message": "Strategic Meta-Plan Generated",
                "details": [/* plan structure */]
              }
            }
          },
          {
            "action": {
              "tool_name": "TDA_SystemLog",
              "arguments": {
                "message": "Plan Optimization",
                "details": "FASTPATH initiated for 'base_databaseList'."
              }
            }
          },
          {
            "action": {
              "tool_name": "base_databaseList",
              "arguments": {}
            },
            "result": {
              "status": "success",
              "results": [/* database list */]
            }
          }
        ]
      }
    ]
  }
}
```

---

## Optimization Insights for @OPTIM

### Common Issues to Detect

1. **Excessive Strategic Planning Overhead**
   - **Symptom**: High token count in strategic planning LLM call (>10K tokens)
   - **Cause**: Too much context (full tool descriptions, large history)
   - **Fix**: Enable context distillation, tool condensation after first turn

2. **Missed FASTPATH Opportunities**
   - **Symptom**: Tactical LLM calls when only 1 relevant tool exists
   - **Cause**: FASTPATH logic not triggered
   - **Fix**: Review `relevant_tools` filtering in strategic plan

3. **Recursive Execution Loops**
   - **Symptom**: Same tool called multiple times in execution trace
   - **Cause**: Self-correction loop without progress, or plan includes recursion
   - **Fix**: Add cycle detection, limit max tool retries

4. **Inappropriate LLM Result Formats**
   - **Symptom**: LLM returns malformed JSON, missing fields, or incorrect structure
   - **Cause**: Prompts don't clearly specify format, or model doesn't follow instructions
   - **Fix**: Add stricter format validation in prompts, use structured output schemas

5. **Redundant Tool Calls**
   - **Symptom**: Same query executed twice (e.g., schema lookup in Phase 1 & 2)
   - **Cause**: Plan hydration not working, or phases don't share context
   - **Fix**: Enable plan hydration, pass previous phase results

### Metrics for Optimization

**Token Efficiency:**
```python
# Per-LLM-call efficiency
tokens_per_llm_call = total_tokens / llm_call_count

# Overhead ratio (how much extra context vs useful data)
overhead_ratio = (strategic_plan_tokens / total_tokens) * 100

# FASTPATH effectiveness (% of phases that skipped tactical planning)
fastpath_rate = (fastpath_phases / total_phases) * 100
```

**Execution Speed:**
```python
# Time per token
ms_per_token = total_duration_ms / total_tokens

# Phase duration breakdown
phase_durations = [phase['duration_ms'] for phase in execution_trace]
avg_phase_duration = sum(phase_durations) / len(phase_durations)
```

**Quality Indicators:**
```python
# Success rate
success_rate = successful_tool_calls / total_tool_calls

# Self-correction frequency (higher = more errors)
correction_rate = workaround_events / total_phases
```

---

## Comparison Methodology

### Fair Comparisons

**What to Compare:**
- Total execution time (wall-clock)
- Total tokens consumed (input + output)
- Cost per query (if pricing available)
- Time per token (accounts for different token usage)

**What NOT to Compare Directly:**
- LLM call count (architecture difference)
- Token overhead (expected to differ by design)
- Execution phases (different architectures)

### Context-Specific Analysis

**For Simple Queries (1-2 steps):**
- **Winner**: Profile with lower time + cost
- **Expectation**: @IDEAT should win (no planning overhead)

**For Complex Queries (3+ steps):**
- **Winner**: Profile with higher success rate + better answer quality
- **Expectation**: @OPTIM should win (strategic planning adds value)

---

## Usage Examples

### Example 1: Basic Comparison

```bash
python3 profile_performance_test.py \
  --query "how many databases are on the system?" \
  --profile1 IDEAT \
  --profile2 OPTIM \
  --timeout 120
```

**Expected Output:**
```
[ 3/7] Executing query with IDEAT...
    ✓ Completed in 3.23s
      Tokens: 16,085 in / 352 out
      LLM calls: 2

[ 4/7] Executing query with OPTIM...
    ✓ Completed in 20.33s
      Tokens: 10,698 in / 1,300 out
      LLM calls: 0
```

**Interpretation:**
- IDEAT: Faster (3.23s vs 20.33s) due to no strategic planning
- OPTIM: Fewer input tokens (10,698 vs 16,085) due to context optimization
- OPTIM: More output tokens (1,300 vs 352) due to structured report generation
- Winner for simple query: IDEAT (faster + lower overhead)

### Example 2: Analyze OPTIM Strategic Plan

After running the test, inspect the session file:

```bash
# Find session file
USER_UUID="38a49547-611a-49dd-b73f-68fd647e8d46"
SESSION_ID="<session_id_from_test_output>"

# Extract strategic plan
cat tda_sessions/$USER_UUID/$SESSION_ID.json | \
  jq '.last_turn_data.workflow_history[0].original_plan'
```

**Output:**
```json
[
  {
    "phase": 1,
    "goal": "Get the list of all databases on the Teradata system",
    "relevant_tools": ["base_databaseList"],
    "arguments": {}
  },
  {
    "phase": 2,
    "goal": "Generate the final report based on the data gathered.",
    "relevant_tools": ["TDA_FinalReport"],
    "arguments": {}
  }
]
```

**Analysis:**
- 2-phase plan for simple query (potentially over-engineered)
- Phase 1: Single relevant tool → FASTPATH should activate
- Phase 2: Report generation (adds overhead for simple queries)
- **Optimization Opportunity**: For single-database-query pattern, could skip strategic planning entirely

### Example 3: Detect FASTPATH Activation

```bash
# Extract execution trace and look for FASTPATH messages
cat tda_sessions/$USER_UUID/$SESSION_ID.json | \
  jq '.last_turn_data.workflow_history[0].execution_trace[] |
      select(.action.tool_name == "TDA_SystemLog") |
      select(.action.arguments.message | contains("FASTPATH"))'
```

**Output:**
```json
{
  "action": {
    "tool_name": "TDA_SystemLog",
    "arguments": {
      "message": "Plan Optimization",
      "details": "FASTPATH initiated for 'base_databaseList'."
    }
  },
  "result": {"status": "info"}
}
```

**Interpretation:**
- FASTPATH activated for Phase 1 (skipped tactical LLM call)
- Saved ~3K-4K tokens by not calling LLM for obvious tool selection
- This is GOOD optimization behavior

### Example 4: Identify Token Bottlenecks

```bash
# Extract LLM call token counts
cat tda_sessions/$USER_UUID/$SESSION_ID.json | \
  jq '.last_turn_data.workflow_history[0].execution_trace[] |
      select(.action.tool_name == "TDA_SystemLog") |
      select(.action.arguments.message | contains("LLM")) |
      .action.arguments.details |
      {summary, input_tokens, output_tokens}'
```

**Output:**
```json
{
  "summary": "Generating a strategic meta-plan for the goal",
  "input_tokens": 7376,
  "output_tokens": 262
}
```

**Analysis:**
- Strategic planning: 7,376 input tokens (HIGH for simple query)
- Output: 262 tokens (reasonable for 2-phase plan)
- **Optimization Opportunity**: Strategic planning prompt may include unnecessary context
- **Action**: Review prompt to reduce tool descriptions, system instructions, or history

---

## Troubleshooting

### Issue: Token counts are 0 for OPTIM

**Cause:** Metrics extractor not parsing `token_update` events correctly

**Fix:**
1. Check task result for `token_update` events with `total_input` / `total_output` fields
2. Verify metrics extractor handles `token_update` event type
3. Fall back to session file if task events are incomplete

### Issue: Profile not found

**Cause:** Profile tag mismatch (@ prefix handling)

**Fix:**
```python
# Normalize tag (remove @ if present)
tag = tag.lstrip("@").upper()

# Match against profiles
profile = next((p for p in profiles if p.tag.lstrip("@").upper() == tag), None)
```

### Issue: Session file not found

**Cause:** Session file written asynchronously after task completion

**Fix:**
- Add small delay (1-2 seconds) after task completion
- Retry session file read with exponential backoff
- Gracefully handle missing session file (use task data only)

### Issue: LLM call count is 0 for OPTIM

**Cause:** Task events don't include `conversation_llm_step` events for planner/executor

**Fix:**
- Count strategic + tactical planning calls from `TDA_SystemLog` events
- Look for messages: "Calling LLM for Planning", "Calling LLM for Tactical Selection"
- Extract token counts from `details.input_tokens` / `details.output_tokens`

---

## Extending the Framework

### Add New Profile Type

1. Update `metrics_extractor.py` to handle new event structure
2. Add profile-specific extraction logic (e.g., for `rag_focused` profiles)
3. Update `comparator.py` to include new profile characteristics in report

### Add Custom Metrics

```python
# In metrics_extractor.py
@dataclass
class ExecutionMetrics:
    # ... existing fields ...

    # Add custom metrics
    rag_retrievals: int = 0              # Number of RAG queries
    champion_cases_found: int = 0        # RAG hits
    self_corrections: int = 0            # Error recovery attempts
    planning_overhead_ratio: float = 0.0 # Planning tokens / total tokens
```

### Add Issue Detection

```python
# In comparator.py
def detect_issues(metrics: ExecutionMetrics) -> List[str]:
    issues = []

    # Detect recursive execution
    tool_counts = {}
    for trace in metrics.execution_trace:
        tool = trace.get('tool_name')
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

    for tool, count in tool_counts.items():
        if count > 3:
            issues.append(f"Recursive execution detected: {tool} called {count} times")

    # Detect high overhead
    if metrics.tokens_per_llm_call > 10000:
        issues.append(f"High token overhead: {metrics.tokens_per_llm_call} tokens per LLM call")

    return issues
```

---

## Best Practices

1. **Always use profile override in query submission, not session creation**
   - Create session without profile_id (uses default)
   - Override with profile_id parameter when submitting query
   - This ensures proper REST API behavior

2. **Capture both task results AND session files**
   - Task results: Real-time event stream, token counts
   - Session files: Strategic plans, execution traces, workflow history
   - Merge for complete picture

3. **Focus optimization on @OPTIM profiles**
   - These are prone to complexity and runaway executions
   - Analyze strategic plans for over-engineering
   - Look for FASTPATH opportunities
   - Validate LLM result formats

4. **Test with multiple query types**
   - Simple queries (1-2 steps): Expect @IDEAT to win
   - Complex queries (3+ steps): Expect @OPTIM to win
   - Edge cases: Recursive patterns, large data, format validation

5. **Generate actionable reports**
   - Include specific optimization recommendations
   - Show phase-by-phase token breakdown
   - Highlight FASTPATH activations
   - Flag issues with evidence (execution traces)

---

## Future Enhancements

- [ ] Auto-detection of profile type (tool_enabled vs llm_only) from execution events
- [ ] Multi-query batch testing with statistical analysis
- [ ] Cost tracking integration with provider pricing APIs
- [ ] RAG effectiveness scoring (champion case usage rate)
- [ ] Regression testing (compare against baseline metrics)
- [ ] A/B testing framework (same query, different LLM providers)
- [ ] Issue detection algorithms (recursive execution, format validation)
- [ ] Prompt optimization suggestions based on token analysis
- [ ] Real-time monitoring dashboard (WebSocket-based)
- [ ] Integration with CI/CD pipelines for automated testing

---

## References

- **Framework Location:** `test/performance/`
- **Main Script:** `profile_performance_test.py`
- **REST API Docs:** `docs/RestAPI/restAPI.md`
- **Profile Architecture:** `CLAUDE.md` → Profile System Architecture
- **Context Window Management:** `docs/Architecture/CONTEXT_WINDOW_ARCHITECTURE.md`
- **Planner/Executor Deep Dive:** `CLAUDE.md` → Deep Dive: Planner/Executor Architecture

---

## Changelog

**v1.0.0 (2026-02-09)**
- Initial skill creation
- Core framework implementation (client, extractor, comparator)
- Support for @IDEAT (llm_only) and @OPTIM (tool_enabled) profiles
- Dual-format reports (JSON + Markdown)
- Session file integration for strategic plan analysis
- FASTPATH detection
- Token efficiency metrics
- Execution trace extraction
