"""
Profile comparison engine for side-by-side performance analysis.

Used by profile_performance_test.py to compare ExecutionMetrics
from two different profiles run against the same query.
"""

from dataclasses import dataclass, field
from metrics_extractor import ExecutionMetrics


@dataclass
class ComparisonResult:
    profile1: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    profile2: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    token_difference: dict = field(default_factory=dict)
    time_difference: dict = field(default_factory=dict)
    winner: dict = field(default_factory=dict)


class ProfileComparator:
    """Compare two profile executions side-by-side."""

    @staticmethod
    def compare(metrics1: ExecutionMetrics, metrics2: ExecutionMetrics) -> ComparisonResult:
        """Compute comparison between two profile executions."""
        result = ComparisonResult(profile1=metrics1, profile2=metrics2)

        # Token differences
        input_diff = metrics1.total_input_tokens - metrics2.total_input_tokens
        output_diff = metrics1.total_output_tokens - metrics2.total_output_tokens
        total_diff = metrics1.total_tokens - metrics2.total_tokens

        base_tokens = max(metrics1.total_tokens, 1)
        result.token_difference = {
            "input": {
                "profile1": metrics1.total_input_tokens,
                "profile2": metrics2.total_input_tokens,
                "absolute": input_diff,
                "percentage": (input_diff / max(metrics1.total_input_tokens, 1)) * 100,
            },
            "output": {
                "profile1": metrics1.total_output_tokens,
                "profile2": metrics2.total_output_tokens,
                "absolute": output_diff,
                "percentage": (output_diff / max(metrics1.total_output_tokens, 1)) * 100,
            },
            "total": {
                "profile1": metrics1.total_tokens,
                "profile2": metrics2.total_tokens,
                "absolute": total_diff,
                "percentage": (total_diff / base_tokens) * 100,
            },
        }

        # Time differences
        time_diff = metrics1.total_duration_ms - metrics2.total_duration_ms
        base_time = max(metrics1.total_duration_ms, 1)
        result.time_difference = {
            "profile1_ms": metrics1.total_duration_ms,
            "profile2_ms": metrics2.total_duration_ms,
            "absolute_ms": time_diff,
            "percentage": (time_diff / base_time) * 100,
        }

        # Winners (lower is better for all metrics)
        tag1 = metrics1.profile_tag or "Profile1"
        tag2 = metrics2.profile_tag or "Profile2"

        result.winner = {
            "tokens": tag1 if metrics1.total_tokens <= metrics2.total_tokens else tag2,
            "time": tag1 if metrics1.total_duration_ms <= metrics2.total_duration_ms else tag2,
            "efficiency": (
                tag1 if metrics1.tokens_per_llm_call <= metrics2.tokens_per_llm_call else tag2
            ),
        }

        return result

    @staticmethod
    def generate_json_report(comparison: ComparisonResult, query: str, timestamp: str) -> dict:
        """Generate JSON report for profile comparison."""
        m1 = comparison.profile1
        m2 = comparison.profile2
        return {
            "test_metadata": {
                "timestamp": timestamp,
                "query": query,
                "profile1_tag": m1.profile_tag,
                "profile2_tag": m2.profile_tag,
            },
            "profile1": {
                "tag": m1.profile_tag,
                "execution_path": m1.execution_path,
                "total_tokens": m1.total_tokens,
                "input_tokens": m1.total_input_tokens,
                "output_tokens": m1.total_output_tokens,
                "duration_ms": m1.total_duration_ms,
                "llm_calls": m1.llm_call_count,
                "tokens_per_llm_call": round(m1.tokens_per_llm_call, 1),
                "tool_calls": m1.tool_calls,
                "self_corrections": m1.self_correction_count,
                "fast_path": m1.fast_path_count,
                "slow_path": m1.slow_path_count,
            },
            "profile2": {
                "tag": m2.profile_tag,
                "execution_path": m2.execution_path,
                "total_tokens": m2.total_tokens,
                "input_tokens": m2.total_input_tokens,
                "output_tokens": m2.total_output_tokens,
                "duration_ms": m2.total_duration_ms,
                "llm_calls": m2.llm_call_count,
                "tokens_per_llm_call": round(m2.tokens_per_llm_call, 1),
                "tool_calls": m2.tool_calls,
                "self_corrections": m2.self_correction_count,
                "fast_path": m2.fast_path_count,
                "slow_path": m2.slow_path_count,
            },
            "comparison": {
                "token_difference": comparison.token_difference,
                "time_difference": comparison.time_difference,
                "winner": comparison.winner,
            },
        }

    @staticmethod
    def generate_markdown_report(comparison: ComparisonResult, query: str, timestamp: str) -> str:
        """Generate Markdown report for profile comparison."""
        m1 = comparison.profile1
        m2 = comparison.profile2
        tag1 = m1.profile_tag or "Profile1"
        tag2 = m2.profile_tag or "Profile2"

        lines = []
        lines.append("# Profile Performance Comparison Report")
        lines.append("")
        lines.append(f"**Generated**: {timestamp}")
        lines.append(f"**Query**: \"{query}\"")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Comparison table
        lines.append("## Comparison")
        lines.append("")
        lines.append(f"| Metric | {tag1} | {tag2} | Winner |")
        lines.append("|--------|--------|--------|--------|")

        lines.append(f"| **Execution Path** | {m1.execution_path} | {m2.execution_path} | - |")
        lines.append(f"| **Total Tokens** | {m1.total_tokens:,} | {m2.total_tokens:,} | {comparison.winner['tokens']} |")
        lines.append(f"| **Input Tokens** | {m1.total_input_tokens:,} | {m2.total_input_tokens:,} | - |")
        lines.append(f"| **Output Tokens** | {m1.total_output_tokens:,} | {m2.total_output_tokens:,} | - |")
        lines.append(f"| **Duration** | {m1.total_duration_ms / 1000:.1f}s | {m2.total_duration_ms / 1000:.1f}s | {comparison.winner['time']} |")
        lines.append(f"| **LLM Calls** | {m1.llm_call_count} | {m2.llm_call_count} | - |")
        lines.append(f"| **Tokens/Call** | {m1.tokens_per_llm_call:.0f} | {m2.tokens_per_llm_call:.0f} | {comparison.winner['efficiency']} |")
        lines.append(f"| **Self-Corrections** | {m1.self_correction_count} | {m2.self_correction_count} | - |")

        tools1 = ", ".join(m1.tool_calls) if m1.tool_calls else "None"
        tools2 = ", ".join(m2.tool_calls) if m2.tool_calls else "None"
        lines.append(f"| **Tools Used** | {tools1} | {tools2} | - |")
        lines.append("")

        # Differences
        lines.append("## Differences")
        lines.append("")
        td = comparison.token_difference["total"]
        tt = comparison.time_difference
        lines.append(f"- Token difference: {td['absolute']:+,} ({td['percentage']:+.1f}%)")
        lines.append(f"- Time difference: {tt['absolute_ms'] / 1000:+.2f}s ({tt['percentage']:+.1f}%)")
        lines.append("")

        # Recommendation
        lines.append("## Recommendation")
        lines.append("")
        if comparison.winner["time"] == comparison.winner["tokens"]:
            lines.append(f"{comparison.winner['time']} is both faster and more token-efficient for this query.")
        else:
            lines.append(
                f"Trade-off: {comparison.winner['time']} is faster, "
                f"but {comparison.winner['tokens']} uses fewer tokens."
            )
        lines.append("")

        return "\n".join(lines)
