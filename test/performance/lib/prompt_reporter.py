"""
Report generation for MCP tool/prompt test results.

Generates JSON reports, Markdown reports, and console summary tables.
Output format matches the existing report structure from previous test runs.
"""

from dataclasses import dataclass, field


@dataclass
class TestSummary:
    total_fixtures: int = 0
    passed: int = 0
    failed: int = 0
    warned: int = 0
    errored: int = 0
    total_tokens: int = 0
    total_duration_ms: int = 0
    total_self_corrections: int = 0
    avg_tokens_per_prompt: float = 0.0
    avg_duration_ms: float = 0.0


class PromptReporter:
    """Generate reports from PromptAnalysis results."""

    @staticmethod
    def compute_summary(analyses: list) -> TestSummary:
        """Aggregate all analyses into a summary."""
        s = TestSummary()
        s.total_fixtures = len(analyses)
        for a in analyses:
            v = a.verdict
            if v == "PASS":
                s.passed += 1
            elif v == "FAIL":
                s.failed += 1
            elif v == "WARN":
                s.warned += 1
            elif v == "ERROR":
                s.errored += 1
            s.total_tokens += a.tokens.get("total", 0)
            s.total_duration_ms += a.duration_ms
            s.total_self_corrections += a.self_correction.count
        if s.total_fixtures > 0:
            s.avg_tokens_per_prompt = s.total_tokens / s.total_fixtures
            s.avg_duration_ms = s.total_duration_ms / s.total_fixtures
        return s

    @staticmethod
    def generate_json_report(analyses: list, summary: TestSummary, metadata: dict) -> dict:
        """Generate JSON report matching existing output format."""
        results = []
        for a in analyses:
            r = {
                "fixture_id": a.fixture_id,
                "prompt_name": a.prompt_name,
                "verdict": a.verdict,
                "verdict_reasons": a.verdict_reasons,
                "status": a.status,
                "task_id": a.task_id,
                "session_id": a.session_id,
                "duration_ms": a.duration_ms,
                "execution_mode": a.execution_mode,
                "tokens": a.tokens,
                "self_correction": {
                    "count": a.self_correction.count,
                    "types": a.self_correction.types,
                    "none_value_errors": a.self_correction.none_value_errors,
                    "llm_correction_calls": a.self_correction.llm_correction_calls,
                    "details": a.self_correction.correction_details,
                },
                "plan_quality": {
                    "phase_count": a.plan_quality.phase_count,
                    "tools_invoked": a.plan_quality.tools_invoked,
                    "orchestrators_used": a.plan_quality.orchestrators_used,
                    "fast_path_count": a.plan_quality.fast_path_count,
                    "slow_path_count": a.plan_quality.slow_path_count,
                    "safeguards_fired": a.plan_quality.safeguards_fired,
                    "has_final_report": a.plan_quality.has_final_report,
                    "rewrite_passes_fired": a.plan_quality.rewrite_passes_fired,
                },
                "parameter_resolution": {
                    "all_resolved": a.parameter_resolution.all_resolved,
                    "resolved": a.parameter_resolution.resolved,
                    "unresolved": a.parameter_resolution.unresolved,
                },
                "issues": a.issues,
                "execution_errors": [
                    {
                        "error_message": e.error_message,
                        "error_type": e.error_type,
                        "phases_completed": e.phases_completed,
                        "partial_input_tokens": e.partial_input_tokens,
                        "partial_output_tokens": e.partial_output_tokens,
                    }
                    for e in a.execution_errors
                ] if a.execution_errors else [],
            }
            if a.conversation_tools_used:
                r["conversation_tools_used"] = a.conversation_tools_used
            results.append(r)

        return {
            "test_metadata": metadata,
            "summary": {
                "total_fixtures": summary.total_fixtures,
                "passed": summary.passed,
                "failed": summary.failed,
                "warned": summary.warned,
                "errored": summary.errored,
                "total_tokens": summary.total_tokens,
                "total_duration_ms": summary.total_duration_ms,
                "total_self_corrections": summary.total_self_corrections,
                "avg_tokens_per_prompt": summary.avg_tokens_per_prompt,
                "avg_duration_ms": summary.avg_duration_ms,
            },
            "results": results,
        }

    @staticmethod
    def generate_markdown_report(analyses: list, summary: TestSummary, metadata: dict) -> str:
        """Generate Markdown report."""
        lines = []
        test_type = metadata.get("test_type", "prompt")
        profile_tag = metadata.get("profile_tag", "default")

        lines.append(f"# MCP {test_type.title()} Performance Test Report")
        lines.append("")
        lines.append(f"**Generated**: {metadata.get('timestamp', 'N/A')}")
        lines.append(f"**Server**: {metadata.get('server_url', 'N/A')}")
        lines.append(f"**Profile**: @{profile_tag}")
        lines.append(f"**Fixtures**: {metadata.get('fixtures_file', 'N/A')} ({summary.total_fixtures} fixtures)")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Summary table
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| **Total Fixtures** | {summary.total_fixtures} |")
        lines.append(f"| **Passed** | {summary.passed} |")
        lines.append(f"| **Failed** | {summary.failed} |")
        lines.append(f"| **Warned** | {summary.warned} |")
        lines.append(f"| **Errored** | {summary.errored} |")
        lines.append(f"| **Total Tokens** | {summary.total_tokens:,} |")
        lines.append(f"| **Total Duration** | {summary.total_duration_ms / 1000:.1f}s |")
        lines.append(f"| **Self-Corrections** | {summary.total_self_corrections} |")
        lines.append(f"| **Avg Tokens/Fixture** | {summary.avg_tokens_per_prompt:,.0f} |")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Individual results
        lines.append("## Results")
        lines.append("")
        for a in analyses:
            lines.append(f"### [{a.verdict}] {a.prompt_name} ({a.fixture_id})")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| **Status** | {a.status} |")
            lines.append(f"| **Mode** | {a.execution_mode} |")
            lines.append(f"| **Duration** | {a.duration_ms / 1000:.1f}s |")
            lines.append(f"| **Input Tokens** | {a.tokens.get('input', 0):,} |")
            lines.append(f"| **Output Tokens** | {a.tokens.get('output', 0):,} |")
            lines.append(f"| **Total Tokens** | {a.tokens.get('total', 0):,} |")
            lines.append(f"| **Self-Corrections** | {a.self_correction.count} |")
            if a.execution_mode == "tool_enabled":
                lines.append(f"| **Fast-Path** | {a.plan_quality.fast_path_count} |")
                lines.append(f"| **Slow-Path** | {a.plan_quality.slow_path_count} |")
            lines.append(f"| **Task ID** | `{a.task_id}` |")
            lines.append(f"| **Session ID** | `{a.session_id}` |")
            lines.append("")

            tools = a.plan_quality.tools_invoked or a.conversation_tools_used
            if tools:
                lines.append(f"**Tools Invoked**: {', '.join(tools)}")
                lines.append("")

            if a.plan_quality.orchestrators_used:
                lines.append(f"**Orchestrators**: {', '.join(a.plan_quality.orchestrators_used)}")
                lines.append("")

            if a.plan_quality.safeguards_fired:
                lines.append(f"**Safeguards**: {', '.join(a.plan_quality.safeguards_fired)}")
                lines.append("")

            if a.parameter_resolution.all_resolved:
                lines.append("**Parameter Resolution**: All arguments resolved")
            else:
                lines.append(f"**Parameter Resolution**: Unresolved: {', '.join(a.parameter_resolution.unresolved)}")
            lines.append("")

            if a.execution_errors:
                for err in a.execution_errors:
                    lines.append(f"**Execution Error**: `{err.error_type}` - {err.error_message[:200]}")
                    lines.append(f"  - Phases completed: {err.phases_completed}, Partial tokens: {err.partial_input_tokens:,}")
                lines.append("")

            if a.verdict != "PASS":
                lines.append(f"**Verdict Reasons**: {'; '.join(a.verdict_reasons)}")
                lines.append("")

            lines.append("---")
            lines.append("")

        # Token analysis table
        lines.append("## Token Analysis")
        lines.append("")
        lines.append("| Fixture | Input | Output | Total | Self-Corrections |")
        lines.append("|---------|-------|--------|-------|------------------|")
        for a in analyses:
            lines.append(
                f"| {a.prompt_name} | {a.tokens.get('input', 0):,} "
                f"| {a.tokens.get('output', 0):,} "
                f"| {a.tokens.get('total', 0):,} "
                f"| {a.self_correction.count} |"
            )
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def print_summary_table(analyses: list, summary: TestSummary) -> None:
        """Print formatted summary table to stdout."""
        print(f"\n{'=' * 80}")
        print("  Test Summary")
        print(f"{'=' * 80}")
        print(f"  Total: {summary.total_fixtures}  |  "
              f"Pass: {summary.passed}  |  "
              f"Fail: {summary.failed}  |  "
              f"Warn: {summary.warned}  |  "
              f"Error: {summary.errored}")
        print(f"  Tokens: {summary.total_tokens:,}  |  "
              f"Duration: {summary.total_duration_ms / 1000:.1f}s  |  "
              f"Self-Corrections: {summary.total_self_corrections}")
        print(f"{'=' * 80}")

        # Per-fixture breakdown
        print(f"\n  {'Fixture':<35} {'Verdict':<8} {'Tokens':>10} {'Time':>8} {'SC':>4}")
        print(f"  {'-' * 70}")
        for a in analyses:
            t = a.tokens.get("total", 0)
            d = f"{a.duration_ms / 1000:.1f}s"
            print(f"  {a.fixture_id:<35} {a.verdict:<8} {t:>10,} {d:>8} {a.self_correction.count:>4}")
        print()
