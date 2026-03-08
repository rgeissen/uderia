#!/usr/bin/env python3
"""
Profile Performance Testing Script for Uderia Platform.

Compares execution performance between different profiles by running
the same query through multiple profiles and analyzing the results.
"""

import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from uderia_client import UderiaClient, UderiaClientError, Profile
from metrics_extractor import MetricsExtractor, ExecutionMetrics
from comparator import ProfileComparator, ComparisonResult


def main():
    """Main entry point for the performance testing script."""
    parser = argparse.ArgumentParser(
        description="Compare performance between Uderia profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare @IDEAT and @OPTIM profiles
  python profile_performance_test.py \\
    --query "how many databases are on the system?" \\
    --profile1 @IDEAT \\
    --profile2 @OPTIM

  # With custom server and timeout
  python profile_performance_test.py \\
    --server http://localhost:5050 \\
    --username admin \\
    --password admin \\
    --query "show me available tables" \\
    --profile1 @IDEAT \\
    --profile2 @OPTIM \\
    --timeout 120 \\
    --output-dir results/
        """
    )

    parser.add_argument(
        "--server",
        default="http://localhost:5050",
        help="Uderia server URL (default: http://localhost:5050)"
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="Username for authentication (default: admin)"
    )
    parser.add_argument(
        "--password",
        default="admin",
        help="Password for authentication (default: admin)"
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Query to execute (required)"
    )
    parser.add_argument(
        "--profile1",
        required=True,
        help="First profile tag (e.g., @IDEAT)"
    )
    parser.add_argument(
        "--profile2",
        required=True,
        help="Second profile tag (e.g., @OPTIM)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Task polling timeout in seconds (default: 60)"
    )
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Output directory for reports (default: results/)"
    )

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(__file__).parent / args.output_dir
    output_dir.mkdir(exist_ok=True)

    # Timestamp for this test run
    timestamp = datetime.now().isoformat()
    timestamp_filename = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 80)
    print("Uderia Profile Performance Comparison")
    print("=" * 80)
    print(f"\nServer: {args.server}")
    print(f"Query: \"{args.query}\"")
    print(f"Profile 1: {args.profile1}")
    print(f"Profile 2: {args.profile2}")
    print(f"Timeout: {args.timeout}s")
    print()

    # Initialize client
    client = UderiaClient(base_url=args.server)

    try:
        # Step 1: Authenticate
        print("[ 1/7] Authenticating...", end=" ", flush=True)
        client.authenticate(args.username, args.password)
        print("✓")

        # Step 2: Find profiles
        print("[ 2/7] Finding profiles...", end=" ", flush=True)
        profile1 = client.find_profile_by_tag(args.profile1)
        profile2 = client.find_profile_by_tag(args.profile2)

        if not profile1:
            print(f"\n\n❌ ERROR: Profile '{args.profile1}' not found\n")
            print(client.list_available_profiles())
            return 1

        if not profile2:
            print(f"\n\n❌ ERROR: Profile '{args.profile2}' not found\n")
            print(client.list_available_profiles())
            return 1

        print("✓")
        print(f"    {profile1.tag}: {profile1.name} ({profile1.profile_type})")
        print(f"    {profile2.tag}: {profile2.name} ({profile2.profile_type})")

        # Execute query for profile 1
        print(f"\n[ 3/7] Executing query with {profile1.tag}...", flush=True)
        metrics1 = execute_profile_query(
            client,
            profile1,
            args.query,
            args.timeout
        )
        print(f"    ✓ Completed in {metrics1.total_duration_ms / 1000:.2f}s")
        print(f"      Tokens: {metrics1.total_input_tokens:,} in / {metrics1.total_output_tokens:,} out")
        print(f"      LLM calls: {metrics1.llm_call_count}")

        # Execute query for profile 2
        print(f"\n[ 4/7] Executing query with {profile2.tag}...", flush=True)
        metrics2 = execute_profile_query(
            client,
            profile2,
            args.query,
            args.timeout
        )
        print(f"    ✓ Completed in {metrics2.total_duration_ms / 1000:.2f}s")
        print(f"      Tokens: {metrics2.total_input_tokens:,} in / {metrics2.total_output_tokens:,} out")
        print(f"      LLM calls: {metrics2.llm_call_count}")

        # Compare results
        print("\n[ 5/7] Comparing results...", end=" ", flush=True)
        comparison = ProfileComparator.compare(metrics1, metrics2)
        print("✓")

        # Generate reports
        print("[ 6/7] Generating reports...", end=" ", flush=True)

        # JSON report
        json_report = ProfileComparator.generate_json_report(
            comparison,
            args.query,
            timestamp
        )
        json_file = output_dir / f"test_run_{timestamp_filename}.json"
        with open(json_file, 'w') as f:
            json.dump(json_report, f, indent=2)

        # Markdown report
        markdown_report = ProfileComparator.generate_markdown_report(
            comparison,
            args.query,
            timestamp
        )
        markdown_file = output_dir / f"comparison_{timestamp_filename}.md"
        with open(markdown_file, 'w') as f:
            f.write(markdown_report)

        print("✓")
        print(f"    JSON:     {json_file}")
        print(f"    Markdown: {markdown_file}")

        # Print summary
        print("\n[ 7/7] Summary")
        print("=" * 80)
        print_comparison_summary(comparison)

        print("\n✓ Test completed successfully!\n")
        return 0

    except UderiaClientError as e:
        print(f"\n\n❌ ERROR: {e}\n")
        return 1
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user\n")
        return 130
    except Exception as e:
        print(f"\n\n❌ UNEXPECTED ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


def execute_profile_query(
    client: UderiaClient,
    profile: Profile,
    query: str,
    timeout: int
) -> ExecutionMetrics:
    """
    Execute a query with a specific profile and extract metrics.

    Args:
        client: UderiaClient instance
        profile: Profile to use
        query: Query string
        timeout: Timeout in seconds

    Returns:
        ExecutionMetrics object

    Raises:
        UderiaClientError: If execution fails
    """
    # Create session WITHOUT profile override (uses default)
    print(f"    Creating session...", end=" ", flush=True)
    session_id = client.create_session()
    print(f"✓ ({session_id})")

    # Submit query WITH profile override
    print(f"    Submitting query with profile override ({profile.tag})...", end=" ", flush=True)
    task_id = client.submit_query(session_id, query, profile_id=profile.id)
    print(f"✓ ({task_id})")

    # Poll for completion
    print(f"    Polling for completion (timeout: {timeout}s)...", end=" ", flush=True)
    task_result = client.poll_task(task_id, timeout=timeout)
    print("✓")

    # Extract metrics from task
    print(f"    Extracting metrics...", end=" ", flush=True)
    task_metrics = MetricsExtractor.extract_from_task(task_result, query)

    # Try to load session file for additional context
    try:
        session_data = client.get_session_file(client.user_uuid, session_id)
        session_metrics = MetricsExtractor.extract_from_session(session_data)

        # Merge metrics
        merged_metrics = MetricsExtractor.merge_metrics(task_metrics, session_metrics)
        print("✓ (with session data)")
        return merged_metrics
    except UderiaClientError as e:
        # Session file not available, use task metrics only
        print("✓ (task data only)")
        return task_metrics


def print_comparison_summary(comparison: ComparisonResult):
    """
    Print a summary of the comparison results.

    Args:
        comparison: ComparisonResult object
    """
    m1 = comparison.profile1
    m2 = comparison.profile2

    print(f"\n{'Metric':<25} {m1.profile_tag:<15} {m2.profile_tag:<15} {'Winner':<10}")
    print("-" * 80)

    # Tokens
    print(f"{'Total Tokens':<25} {m1.total_tokens:<15,} {m2.total_tokens:<15,} {comparison.winner['tokens']:<10}")
    print(f"{'  Input':<25} {m1.total_input_tokens:<15,} {m2.total_input_tokens:<15,}")
    print(f"{'  Output':<25} {m1.total_output_tokens:<15,} {m2.total_output_tokens:<15,}")

    # Time
    time1 = f"{m1.total_duration_ms / 1000:.2f}s"
    time2 = f"{m2.total_duration_ms / 1000:.2f}s"
    print(f"{'Execution Time':<25} {time1:<15} {time2:<15} {comparison.winner['time']:<10}")

    # LLM calls
    print(f"{'LLM Calls':<25} {m1.llm_call_count:<15} {m2.llm_call_count:<15}")

    # Efficiency
    eff1 = f"{m1.tokens_per_llm_call:.1f}"
    eff2 = f"{m2.tokens_per_llm_call:.1f}"
    print(f"{'Tokens/LLM Call':<25} {eff1:<15} {eff2:<15} {comparison.winner['efficiency']:<10}")

    # Tools
    tools1 = ', '.join(m1.tool_calls) if m1.tool_calls else 'None'
    tools2 = ', '.join(m2.tool_calls) if m2.tool_calls else 'None'
    print(f"{'Tools Used':<25} {tools1:<15} {tools2:<15}")

    # Differences
    print("\n" + "Differences".center(80))
    print("-" * 80)

    token_diff = comparison.token_difference['total']
    time_diff = comparison.time_difference

    print(f"Token difference:      {token_diff['absolute']:+,} ({token_diff['percentage']:+.1f}%)")
    print(f"Time difference:       {time_diff['absolute_ms'] / 1000:+.2f}s ({time_diff['percentage']:+.1f}%)")

    # Recommendation
    print("\n" + "Recommendation".center(80))
    print("-" * 80)

    if comparison.winner['time'] == comparison.winner['tokens']:
        print(f"✓ {comparison.winner['time']} is both faster and more token-efficient for this query.")
    else:
        print(f"Trade-off: {comparison.winner['time']} is faster, but {comparison.winner['tokens']} uses fewer tokens.")


if __name__ == "__main__":
    sys.exit(main())
