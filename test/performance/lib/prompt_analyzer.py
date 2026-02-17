"""
Execution trace analyzer for MCP tool/prompt tests.

Parses task events to extract metrics, detect execution mode (tool_enabled
vs conversation), compute plan quality indicators, and assign PASS/FAIL/WARN
verdicts against fixture expectations.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SelfCorrectionInfo:
    count: int = 0
    types: list = field(default_factory=list)
    none_value_errors: int = 0
    llm_correction_calls: int = 0
    correction_details: list = field(default_factory=list)


@dataclass
class PlanQualityInfo:
    phase_count: int = 0
    tools_invoked: list = field(default_factory=list)
    orchestrators_used: list = field(default_factory=list)
    fast_path_count: int = 0
    slow_path_count: int = 0
    safeguards_fired: list = field(default_factory=list)
    has_final_report: bool = False
    rewrite_passes_fired: list = field(default_factory=list)


@dataclass
class ExecutionErrorInfo:
    error_message: str = ""
    error_type: str = ""
    phases_completed: int = 0
    partial_input_tokens: int = 0
    partial_output_tokens: int = 0


@dataclass
class ParameterResolutionInfo:
    all_resolved: bool = True
    resolved: dict = field(default_factory=dict)
    unresolved: list = field(default_factory=list)


@dataclass
class PromptAnalysis:
    fixture_id: str = ""
    prompt_name: str = ""
    status: str = "unknown"
    verdict: str = "UNKNOWN"
    verdict_reasons: list = field(default_factory=list)
    task_id: str = ""
    session_id: str = ""
    duration_ms: int = 0
    tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0, "total": 0})
    self_correction: SelfCorrectionInfo = field(default_factory=SelfCorrectionInfo)
    plan_quality: PlanQualityInfo = field(default_factory=PlanQualityInfo)
    parameter_resolution: ParameterResolutionInfo = field(default_factory=ParameterResolutionInfo)
    issues: list = field(default_factory=list)
    execution_mode: str = "tool_enabled"
    conversation_tools_used: list = field(default_factory=list)
    execution_errors: list = field(default_factory=list)


class PromptAnalyzer:
    """Analyze task results against fixture expectations."""

    def analyze(self, fixture: dict, result) -> PromptAnalysis:
        """Analyze a TaskResult against fixture expectations.

        Args:
            fixture: Fixture dict from the JSON file.
            result: TaskResult from PromptClient.poll_task().
        """
        analysis = PromptAnalysis(
            fixture_id=fixture.get("id", ""),
            prompt_name=fixture.get("expected_tool") or fixture.get("prompt_name", ""),
            status=result.status,
            task_id=result.task_id,
            session_id=getattr(result, "session_id", ""),
            duration_ms=result.duration_ms,
        )

        events = result.events or []

        # Detect execution mode
        analysis.execution_mode = self._detect_mode(events)

        # Extract tokens
        analysis.tokens = self._extract_tokens(events)

        # Extract execution errors (applies to all modes)
        analysis.execution_errors = self._extract_execution_errors(events)

        # Mode-specific extraction
        if analysis.execution_mode == "conversation":
            self._extract_conversation_events(events, analysis)
        else:
            self._extract_tool_enabled_events(events, analysis)

        # Enrich tools_invoked from session execution trace (captures orchestrator-wrapped calls)
        session_data = getattr(result, "session_data", None)
        if session_data:
            self._enrich_from_session_trace(session_data, analysis)

        # Check parameter resolution
        analysis.parameter_resolution = self._check_parameters(fixture, events)

        # Compute verdict
        analysis.verdict, analysis.verdict_reasons = self._compute_verdict(
            fixture, analysis
        )

        return analysis

    # ------------------------------------------------------------------
    # Mode detection
    # ------------------------------------------------------------------

    def _detect_mode(self, events: list) -> str:
        """Detect if execution used conversation agent or planner/executor."""
        for ev in events:
            ed = ev.get("event_data", {})
            if isinstance(ed, dict):
                evt_type = ed.get("type", "")
                if evt_type in (
                    "conversation_agent_start",
                    "conversation_agent_complete",
                ):
                    return "conversation"
        return "tool_enabled"

    # ------------------------------------------------------------------
    # Token extraction
    # ------------------------------------------------------------------

    def _extract_tokens(self, events: list) -> dict:
        """Extract final token counts from token_update events."""
        total_in = 0
        total_out = 0
        for ev in reversed(events):
            if ev.get("event_type") == "token_update":
                td = ev.get("event_data", {})
                total_in = td.get("total_input", 0)
                total_out = td.get("total_output", 0)
                break
        return {"input": total_in, "output": total_out, "total": total_in + total_out}

    # ------------------------------------------------------------------
    # Execution error extraction
    # ------------------------------------------------------------------

    def _extract_execution_errors(self, events: list) -> list:
        """Scan events for execution_error lifecycle events.

        These are emitted via _emit_lifecycle_event as notification events
        with type="execution_error" in the event_data.
        """
        errors = []
        for ev in events:
            if ev.get("event_type") != "notification":
                continue
            ed = ev.get("event_data", {})
            if not isinstance(ed, dict):
                continue
            if ed.get("type") != "execution_error":
                continue
            payload = ed.get("payload", {})
            if not isinstance(payload, dict):
                payload = ed
            errors.append(ExecutionErrorInfo(
                error_message=payload.get("error_message", str(ed)),
                error_type=payload.get("error_type", "unknown"),
                phases_completed=payload.get("phases_completed", 0),
                partial_input_tokens=payload.get("partial_input_tokens", 0),
                partial_output_tokens=payload.get("partial_output_tokens", 0),
            ))
        return errors

    # ------------------------------------------------------------------
    # Conversation mode extraction
    # ------------------------------------------------------------------

    def _extract_conversation_events(self, events: list, analysis: PromptAnalysis):
        """Parse conversation agent events."""
        tools_used = []
        for ev in events:
            ed = ev.get("event_data", {})
            if not isinstance(ed, dict):
                continue
            evt_type = ed.get("type", "")
            payload = ed.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}

            if evt_type == "conversation_tool_invoked":
                tool_name = payload.get("tool_name", "")
                if tool_name:
                    tools_used.append(tool_name)

            elif evt_type == "conversation_agent_complete":
                # Final summary — may have tools_used list
                if "tools_used" in payload:
                    for t in payload["tools_used"]:
                        if t not in tools_used:
                            tools_used.append(t)

            elif evt_type == "conversation_llm_step":
                analysis.plan_quality.slow_path_count += 1

        analysis.conversation_tools_used = tools_used
        analysis.plan_quality.tools_invoked = tools_used

    # ------------------------------------------------------------------
    # Tool-enabled mode extraction
    # ------------------------------------------------------------------

    def _extract_tool_enabled_events(self, events: list, analysis: PromptAnalysis):
        """Parse planner/executor events for tool-enabled profiles."""
        sc = SelfCorrectionInfo()
        pq = PlanQualityInfo()

        for ev in events:
            ed = ev.get("event_data", {})
            if not isinstance(ed, dict):
                continue
            evt_type = ed.get("type", "")
            payload = ed.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}

            # LLM step (both modes)
            if evt_type == "conversation_llm_step":
                step_name = payload.get("step_name", "")
                if "FASTPATH" in step_name.upper():
                    pq.fast_path_count += 1
                else:
                    pq.slow_path_count += 1

            # Tool invocation via notification
            if evt_type == "notification":
                msg = ed.get("message", "")
                ntf_type = ed.get("type", "")

                # Some events are nested under payload
                if ntf_type == "conversation_llm_step":
                    step_name = payload.get("step_name", "")
                    if "FASTPATH" in step_name.upper():
                        pq.fast_path_count += 1
                    else:
                        pq.slow_path_count += 1

            # Tool result events
            if ev.get("event_type") == "tool_result":
                if isinstance(ed, dict):
                    details = ed.get("details", {})
                    if isinstance(details, dict):
                        tool_name = details.get("metadata", {}).get("tool_name", "")
                        if tool_name and tool_name not in pq.tools_invoked:
                            pq.tools_invoked.append(tool_name)

            # Status/notification events containing tool/orchestrator info
            if ev.get("event_type") == "notification":
                ntf_payload = ed.get("payload", ed)
                if isinstance(ntf_payload, dict):
                    ntf_type2 = ntf_payload.get("type", ed.get("type", ""))

                    # Tool invoked via status_indicator_update or similar
                    tool_nm = ntf_payload.get("tool_name", "")
                    if tool_nm and tool_nm not in pq.tools_invoked:
                        pq.tools_invoked.append(tool_nm)

                    # Orchestrators
                    orch_type = ntf_payload.get("orchestrator_type", "")
                    if orch_type and orch_type not in pq.orchestrators_used:
                        pq.orchestrators_used.append(orch_type)

                    # Safeguards
                    safeguard = ntf_payload.get("safeguard", "")
                    if safeguard and safeguard not in pq.safeguards_fired:
                        pq.safeguards_fired.append(safeguard)

                    # Rewrite passes
                    rewrite = ntf_payload.get("rewrite_pass", "")
                    if rewrite and rewrite not in pq.rewrite_passes_fired:
                        pq.rewrite_passes_fired.append(rewrite)

            # Parse TDA_SystemLog messages from tool_result events
            if ev.get("event_type") == "tool_result":
                details = ed.get("details", {}) if isinstance(ed, dict) else {}
                if isinstance(details, dict):
                    meta = details.get("metadata", {})
                    tool_name = meta.get("tool_name", "")

                    if tool_name == "TDA_SystemLog":
                        log_msg = str(details.get("results", ""))
                        self._parse_system_log(log_msg, pq, sc)

                    elif tool_name in ("TDA_FinalReport", "TDA_ComplexPromptReport"):
                        pq.has_final_report = True

                    elif tool_name == "TDA_SystemOrchestration":
                        orch_info = details.get("results", "")
                        if "date_range" in str(orch_info).lower():
                            if "date_range" not in pq.orchestrators_used:
                                pq.orchestrators_used.append("date_range")
                        if "column_iteration" in str(orch_info).lower():
                            if "column_iteration" not in pq.orchestrators_used:
                                pq.orchestrators_used.append("column_iteration")

        # Also scan for tool names in any notification event_data
        for ev in events:
            ed = ev.get("event_data", {})
            if isinstance(ed, dict):
                evt_type = ed.get("type", "")
                payload = ed.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}

                # conversation_llm_step has step_name with tool info
                if evt_type == "conversation_llm_step":
                    step_name = payload.get("step_name", "")
                    # Extract tool name from step patterns like "Phase 1: Execute base_tableDDL"
                    for word in step_name.split():
                        if "_" in word and not word.startswith("TDA_"):
                            clean = word.strip("(),:;")
                            if clean and clean not in pq.tools_invoked:
                                pq.tools_invoked.append(clean)

                # Check for final report in step names
                if "TDA_FinalReport" in str(ed) or "TDA_ComplexPromptReport" in str(ed):
                    pq.has_final_report = True

        analysis.self_correction = sc
        analysis.plan_quality = pq

    def _enrich_from_session_trace(self, session_data: dict, analysis: PromptAnalysis):
        """Supplement tools_invoked and self-correction counts from the session's
        execution trace.

        Orchestrator-wrapped tool calls (date range, column iteration) invoke
        tools via mcp_adapter directly and don't emit standard SSE tool events.
        Self-correction events appear as TDA_SystemLog entries with
        metadata.type == "workaround" — the only reliable source for SC counts.
        The session file's execution_trace is the authoritative record.
        """
        try:
            wh = session_data.get("last_turn_data", {}).get("workflow_history", [])
            if not wh:
                return
            sc = analysis.self_correction
            trace = wh[0].get("execution_trace", [])
            for entry in trace:
                action = entry.get("action", {})
                if not isinstance(action, dict):
                    continue
                tool_name = action.get("tool_name", "")
                if (
                    tool_name
                    and tool_name != "TDA_SystemLog"
                    and tool_name not in analysis.plan_quality.tools_invoked
                ):
                    analysis.plan_quality.tools_invoked.append(tool_name)
                elif tool_name == "TDA_SystemLog":
                    meta = action.get("metadata", {}) or {}
                    meta_type = meta.get("type", "")
                    args = action.get("arguments", {}) or {}
                    details = args.get("details", "")

                    # Extract summary text
                    summary = ""
                    if isinstance(details, dict):
                        summary = details.get("summary", "")
                    elif isinstance(details, str):
                        summary = details
                    summary_lower = summary.lower()

                    # --- Self-correction detection ---
                    # Each "Attempting self-correction (N/M)" = 1 retry attempt
                    if meta_type == "workaround" and "attempting self-correction" in summary_lower:
                        sc.count += 1
                        sc_type = "tool_error"
                        inner = details.get("details", {}) if isinstance(details, dict) else {}
                        error_msg = str(inner.get("error", "")).lower() if isinstance(inner, dict) else ""
                        if "none" in error_msg and "type" in error_msg:
                            sc.none_value_errors += 1
                            sc_type = "none_value"
                        elif "schema" in error_msg or "validation" in error_msg:
                            sc_type = "schema_validation"
                        sc.types.append(sc_type)
                        sc.correction_details.append({"type": sc_type, "summary": summary[:120]})

                    # Count LLM correction calls (LLM proposes new arguments)
                    if meta_type == "workaround" and "llm proposed" in summary_lower:
                        sc.llm_correction_calls += 1

                    # --- Orchestrator / column iteration detection ---
                    details_str = str(details)
                    match = re.search(
                        r"column iteration for ['\"](\w+)['\"]", details_str
                    )
                    if match:
                        iterated_tool = match.group(1)
                        if iterated_tool not in analysis.plan_quality.tools_invoked:
                            analysis.plan_quality.tools_invoked.append(iterated_tool)
                        if "column_iteration" not in analysis.plan_quality.orchestrators_used:
                            analysis.plan_quality.orchestrators_used.append("column_iteration")
                    details_lower = details_str.lower()
                    if "date range" in details_lower or "date_range" in details_lower:
                        if "date_range" not in analysis.plan_quality.orchestrators_used:
                            analysis.plan_quality.orchestrators_used.append("date_range")
        except (KeyError, IndexError, TypeError):
            pass  # Session data may not have expected structure

    def _parse_system_log(self, msg: str, pq: PlanQualityInfo, sc: SelfCorrectionInfo):
        """Extract indicators from TDA_SystemLog messages."""
        msg_lower = msg.lower()

        # Self-correction indicators
        if "self-correction" in msg_lower or "self_correction" in msg_lower:
            sc.count += 1
            sc_type = "unknown"
            if "none" in msg_lower and "type" in msg_lower:
                sc.none_value_errors += 1
                sc_type = "none_value"
            elif "schema" in msg_lower or "validation" in msg_lower:
                sc_type = "schema_validation"
            elif "retry" in msg_lower:
                sc_type = "retry"
            sc.types.append(sc_type)
            sc.correction_details.append({"type": sc_type, "summary": msg[:120]})

        if "llm correction" in msg_lower:
            sc.llm_correction_calls += 1

        # Fast path
        if "fastpath" in msg_lower or "fast-path" in msg_lower or "fast_path" in msg_lower:
            pass  # Already counted via llm_step events

        # Safeguards
        for sg in [
            "proactive_replan",
            "autonomous_recovery",
            "error_correction",
            "redundancy_detection",
            "scope_guard",
            "budget_guard",
        ]:
            if sg in msg_lower:
                if sg not in pq.safeguards_fired:
                    pq.safeguards_fired.append(sg)

        # Orchestrators — match both underscore and space variants
        # (log messages use spaces, e.g. "column iteration", but we
        #  normalize to underscore for the canonical name)
        _ORCH_PATTERNS = [
            ("date_range", ["date_range", "date range"]),
            ("column_iteration", ["column_iteration", "column iteration"]),
            ("hallucinated_loop", ["hallucinated_loop", "hallucinated loop"]),
        ]
        for canonical, variants in _ORCH_PATTERNS:
            if any(v in msg_lower for v in variants):
                if canonical not in pq.orchestrators_used:
                    pq.orchestrators_used.append(canonical)

        # Extract wrapped tool names from column iteration messages
        # e.g. "column iteration for 'qlty_rowsWithMissingValues'"
        match = re.search(r"column iteration for ['\"](\w+)['\"]", msg)
        if match:
            iterated_tool = match.group(1)
            if iterated_tool not in pq.tools_invoked:
                pq.tools_invoked.append(iterated_tool)

        # Rewrite passes
        for rw in [
            "temporal_flow", "sql_consolidation", "multi_loop_synthesis",
            "scope_alignment", "argument_binding", "phase_dedup",
            "goal_refinement", "tool_routing", "final_validation",
        ]:
            if rw in msg_lower:
                if rw not in pq.rewrite_passes_fired:
                    pq.rewrite_passes_fired.append(rw)

    # ------------------------------------------------------------------
    # Parameter resolution
    # ------------------------------------------------------------------

    def _check_parameters(self, fixture: dict, events: list) -> ParameterResolutionInfo:
        """Check if expected argument values appear in execution events."""
        expected_args = fixture.get("expected_tool_args") or fixture.get("arguments", {})
        if not expected_args:
            return ParameterResolutionInfo()

        # Build a single string from all event data for searching
        event_text = ""
        for ev in events:
            event_text += str(ev.get("event_data", "")) + " "

        info = ParameterResolutionInfo()
        for arg_name, expected_value in expected_args.items():
            # Skip placeholder values
            if isinstance(expected_value, str) and expected_value.startswith("YOUR_"):
                continue
            found = str(expected_value).lower() in event_text.lower()
            info.resolved[arg_name] = found
            if not found:
                info.unresolved.append(arg_name)
                info.all_resolved = False

        return info

    # ------------------------------------------------------------------
    # Verdict
    # ------------------------------------------------------------------

    def _compute_verdict(self, fixture: dict, analysis: PromptAnalysis):
        """Compute PASS/FAIL/WARN verdict based on fixture expectations."""
        issues = []

        # Select expectations based on mode
        if analysis.execution_mode == "conversation" and "conversation_expectations" in fixture:
            expectations = fixture["conversation_expectations"]
        else:
            expectations = fixture.get("expectations", {})

        # 1. Status check
        expected_status = expectations.get("expect_status", "complete")
        if analysis.status != expected_status:
            issues.append(("FAIL", f"Status '{analysis.status}' != expected '{expected_status}'"))

        # 1.5. Execution error check (catches context overflow, API errors that
        #       the executor handles gracefully by setting status="complete")
        for err in analysis.execution_errors:
            issues.append((
                "FAIL",
                f"Execution error ({err.error_type}): {err.error_message[:150]}"
                f" [phases_completed={err.phases_completed},"
                f" partial_tokens={err.partial_input_tokens:,}]"
            ))

        # 2. Expected tool invoked
        expected_tool = fixture.get("expected_tool")
        if expected_tool:
            all_tools = analysis.plan_quality.tools_invoked + analysis.conversation_tools_used
            # Match exact name or handle_ prefix variant (MCP adapter wraps tools)
            tool_found = (
                expected_tool in all_tools
                or f"handle_{expected_tool}" in all_tools
                or any(expected_tool in t for t in all_tools)
            )
            if not tool_found:
                issues.append(("FAIL", f"Expected tool '{expected_tool}' not invoked. Got: {all_tools}"))

        # 3. Self-correction threshold
        max_sc = expectations.get("max_self_corrections")
        if max_sc is not None and analysis.self_correction.count > max_sc:
            issues.append((
                "WARN",
                f"Self-corrections: {analysis.self_correction.count} > max {max_sc}",
            ))

        # 4. Final report check (tool_enabled only, skip for conversation)
        if expectations.get("expect_final_report", False):
            if analysis.execution_mode == "tool_enabled" and not analysis.plan_quality.has_final_report:
                issues.append(("WARN", "No TDA_FinalReport in execution trace"))

        # 5. Orchestrator check
        expected_orch = expectations.get("expect_orchestrator")
        if expected_orch:
            if expected_orch not in analysis.plan_quality.orchestrators_used:
                issues.append((
                    "INFO",
                    f"Expected orchestrator '{expected_orch}' not used "
                    f"(orchestrators: {analysis.plan_quality.orchestrators_used})",
                ))

        # 6. Parameter resolution issues
        if not analysis.parameter_resolution.all_resolved:
            unresolved = analysis.parameter_resolution.unresolved
            issues.append((
                "INFO",
                f"Argument values not confirmed in events: {unresolved}",
            ))

        # Compute final verdict
        has_fail = any(s == "FAIL" for s, _ in issues)
        has_warn = any(s == "WARN" for s, _ in issues)

        if has_fail:
            verdict = "FAIL"
        elif has_warn:
            verdict = "WARN"
        else:
            verdict = "PASS"

        reasons = [r for _, r in issues] if issues else ["All checks passed"]
        return verdict, reasons
