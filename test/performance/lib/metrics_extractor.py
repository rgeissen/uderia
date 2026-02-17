"""
Metrics extraction from Uderia task results and session data.

Used by profile_performance_test.py to extract structured ExecutionMetrics
from task events and session files for comparison.
"""

from dataclasses import dataclass, field


@dataclass
class ExecutionMetrics:
    profile_tag: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_duration_ms: int = 0
    llm_call_count: int = 0
    tokens_per_llm_call: float = 0.0
    ms_per_token: float = 0.0
    tool_calls: list = field(default_factory=list)
    llm_call_durations: list = field(default_factory=list)
    execution_path: str = ""
    self_correction_count: int = 0
    self_correction_types: list = field(default_factory=list)
    rag_used: bool = False
    rag_case_count: int = 0
    orchestrators_used: list = field(default_factory=list)
    fast_path_count: int = 0
    slow_path_count: int = 0
    has_final_report: bool = False


class MetricsExtractor:
    """Extract structured metrics from task results."""

    @staticmethod
    def extract_from_task(task_result, query: str) -> ExecutionMetrics:
        """Extract metrics from a TaskResult's events."""
        m = ExecutionMetrics()
        m.total_duration_ms = task_result.duration_ms
        events = task_result.events or []

        # Detect execution path
        for ev in events:
            ed = ev.get("event_data", {})
            if isinstance(ed, dict):
                if ed.get("type") in ("conversation_agent_start", "conversation_agent_complete"):
                    m.execution_path = "conversation_agent"
                    break
        if not m.execution_path:
            m.execution_path = "planner/executor"

        # Extract tokens from final token_update
        for ev in reversed(events):
            if ev.get("event_type") == "token_update":
                td = ev.get("event_data", {})
                m.total_input_tokens = td.get("total_input", 0)
                m.total_output_tokens = td.get("total_output", 0)
                m.total_tokens = m.total_input_tokens + m.total_output_tokens
                break

        # Parse per-event data
        for ev in events:
            ed = ev.get("event_data", {})
            if not isinstance(ed, dict):
                continue
            evt_type = ed.get("type", "")
            payload = ed.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}

            # LLM steps
            if evt_type == "conversation_llm_step":
                m.llm_call_count += 1
                step_name = payload.get("step_name", "")
                if "FASTPATH" in step_name.upper():
                    m.fast_path_count += 1
                else:
                    m.slow_path_count += 1

            # Tool results (planner/executor mode)
            if ev.get("event_type") == "tool_result":
                details = ed.get("details", {})
                if isinstance(details, dict):
                    tool_name = details.get("metadata", {}).get("tool_name", "")
                    if tool_name and tool_name not in m.tool_calls:
                        m.tool_calls.append(tool_name)
                    if tool_name in ("TDA_FinalReport", "TDA_ComplexPromptReport"):
                        m.has_final_report = True

            # Conversation tool events
            if evt_type == "conversation_tool_invoked":
                tool_name = payload.get("tool_name", "")
                if tool_name and tool_name not in m.tool_calls:
                    m.tool_calls.append(tool_name)

            # RAG retrieval
            if evt_type == "champion_cases_retrieved":
                m.rag_used = True
                cases = payload.get("cases", [])
                m.rag_case_count = len(cases)

            # Self-correction indicators
            if ev.get("event_type") == "tool_result":
                details = ed.get("details", {}) if isinstance(ed, dict) else {}
                if isinstance(details, dict):
                    tool_name = details.get("metadata", {}).get("tool_name", "")
                    if tool_name == "TDA_SystemLog":
                        msg = str(details.get("results", "")).lower()
                        if "self-correction" in msg or "self_correction" in msg:
                            m.self_correction_count += 1

        # Compute derived metrics
        if m.llm_call_count > 0:
            m.tokens_per_llm_call = m.total_tokens / m.llm_call_count
        if m.total_tokens > 0:
            m.ms_per_token = m.total_duration_ms / m.total_tokens

        return m

    @staticmethod
    def extract_from_session(session_data: dict) -> ExecutionMetrics:
        """Extract supplementary metrics from session data."""
        m = ExecutionMetrics()
        # Session data can provide profile info, model, etc.
        m.profile_tag = session_data.get("profile_tag", "")
        return m

    @staticmethod
    def merge_metrics(task_metrics: ExecutionMetrics, session_metrics: ExecutionMetrics) -> ExecutionMetrics:
        """Merge task-level and session-level metrics. Task takes priority."""
        merged = ExecutionMetrics(
            profile_tag=session_metrics.profile_tag or task_metrics.profile_tag,
            total_input_tokens=task_metrics.total_input_tokens,
            total_output_tokens=task_metrics.total_output_tokens,
            total_tokens=task_metrics.total_tokens,
            total_duration_ms=task_metrics.total_duration_ms,
            llm_call_count=task_metrics.llm_call_count,
            tokens_per_llm_call=task_metrics.tokens_per_llm_call,
            ms_per_token=task_metrics.ms_per_token,
            tool_calls=task_metrics.tool_calls,
            execution_path=task_metrics.execution_path,
            self_correction_count=task_metrics.self_correction_count,
            self_correction_types=task_metrics.self_correction_types,
            rag_used=task_metrics.rag_used,
            rag_case_count=task_metrics.rag_case_count,
            orchestrators_used=task_metrics.orchestrators_used,
            fast_path_count=task_metrics.fast_path_count,
            slow_path_count=task_metrics.slow_path_count,
            has_final_report=task_metrics.has_final_report,
        )
        return merged
