#!/usr/bin/env python3
"""
MCP Prompt Performance Test Framework for Uderia Platform.

Exercises MCP prompts end-to-end via the session query REST API,
analyzes execution quality using fusion hardening patterns,
and generates JSON + Markdown reports.

The test creates real sessions so you can watch executions in the UI.

Usage:
    # Run all fixtures
    python mcp_prompt_test.py

    # Discover available prompts and their parameters
    python mcp_prompt_test.py --discover

    # Run only specific prompts
    python mcp_prompt_test.py --filter base_tableBusinessDesc

    # Run fixtures by tag
    python mcp_prompt_test.py --tag quality

    # Custom server and credentials
    python mcp_prompt_test.py --server http://myserver:5050 --username dev --password devpw
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from prompt_client import PromptClient, PromptClientError
from prompt_analyzer import PromptAnalyzer
from prompt_reporter import PromptReporter


def main():
    parser = argparse.ArgumentParser(
        description="MCP Prompt Performance Test Framework for Uderia Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mcp_prompt_test.py                              # Run all fixtures
  python mcp_prompt_test.py --discover                   # List available prompts
  python mcp_prompt_test.py --filter qlty                # Run quality prompts only
  python mcp_prompt_test.py --tag column-scoped          # Run by tag
  python mcp_prompt_test.py --profile-tag OPTIM          # Use specific profile
  python mcp_prompt_test.py --verbose                    # Show event details
        """,
    )
    parser.add_argument("--server", default="http://localhost:5050", help="Uderia server URL")
    parser.add_argument("--username", default="admin", help="Username for authentication")
    parser.add_argument("--password", default="admin", help="Password for authentication")
    parser.add_argument("--fixtures", default="mcp_prompt_fixtures.json", help="Path to fixtures JSON file")
    parser.add_argument("--output-dir", default="results", help="Output directory for reports")
    parser.add_argument("--filter", default=None, help="Substring filter on prompt_name or fixture id")
    parser.add_argument("--tag", action="append", default=None, help="Filter by tag (repeatable)")
    parser.add_argument("--timeout", type=int, default=180, help="Default timeout in seconds")
    parser.add_argument("--profile-tag", default=None, help="Profile tag to use (e.g., OPTIM)")
    parser.add_argument("--discover", action="store_true", help="List available prompts, then exit")
    parser.add_argument("--verbose", action="store_true", help="Show execution event details")
    args = parser.parse_args()

    client = PromptClient(base_url=args.server)

    try:
        # Step 1: Authenticate
        print(f"\n[ 1 ] Authenticating with {args.server}...", end=" ", flush=True)
        client.authenticate(args.username, args.password)
        print("done")

        # Step 2: Discovery mode
        if args.discover:
            return run_discover_mode(client)

        # Step 3: Resolve profile if specified
        profile_id = None
        if args.profile_tag:
            print(f"[ 2 ] Resolving profile @{args.profile_tag}...", end=" ", flush=True)
            profile_id = client.find_profile_by_tag(args.profile_tag)
            if not profile_id:
                print(f"FAILED - profile @{args.profile_tag} not found")
                return 1
            print(f"done ({profile_id[:8]}...)")
        else:
            print("[ 2 ] Using default profile")

        # Step 3: Load fixtures
        print(f"[ 3 ] Loading fixtures...", end=" ", flush=True)
        fixtures = load_fixtures(args.fixtures, args.filter, args.tag, args.timeout)
        if not fixtures:
            print("no fixtures match filter")
            return 0
        print(f"done ({len(fixtures)} fixture{'s' if len(fixtures) != 1 else ''})")

        # Step 4: Execute each fixture
        analyzer = PromptAnalyzer()
        analyses = []

        for i, fixture in enumerate(fixtures, 1):
            fixture_id = fixture["id"]
            prompt_name = fixture["prompt_name"]
            prompt_args = fixture.get("arguments", {})
            timeout = fixture.get("timeout_seconds", args.timeout)

            print(f"\n[{i:2d}/{len(fixtures)}] {prompt_name} ({fixture_id})")
            print(f"       Arguments: {json.dumps(prompt_args)}")

            try:
                # Create session for this fixture (visible in UI)
                session_id = client.create_session()
                print(f"       Session:   {session_id[:12]}...")

                # Submit prompt query
                task_id = client.submit_prompt_query(
                    session_id=session_id,
                    prompt_name=prompt_name,
                    prompt_arguments=prompt_args,
                    profile_id=profile_id,
                )
                print(f"       Task:      {task_id[:12]}...")
                print(f"       Polling    ", end="", flush=True)

                # Poll for results
                result = client.poll_task(task_id, timeout=timeout)
                result.session_id = session_id

                # Print progress indicator
                token_str = ""
                if result.events:
                    # Extract final token count
                    for ev in reversed(result.events):
                        if ev.get("event_type") == "token_update":
                            td = ev.get("event_data", {})
                            total = td.get("total_input", 0) + td.get("total_output", 0)
                            token_str = f" | Tokens: {total:,}"
                            break

                print(
                    f"\r       Status:    {result.status}"
                    f"{token_str}"
                    f" | Duration: {result.duration_ms / 1000:.1f}s"
                )

                # Analyze result
                analysis = analyzer.analyze(fixture, result)

                # Print verdict
                print(f"       Verdict:   [{analysis.verdict}]", end="")
                if analysis.verdict != "PASS":
                    reasons = "; ".join(analysis.verdict_reasons[:2])
                    print(f" - {reasons}")
                else:
                    print()

                # Verbose: show key events
                if args.verbose and analysis.plan_quality.tools_invoked:
                    print(f"       Tools:     {', '.join(analysis.plan_quality.tools_invoked)}")
                if args.verbose and analysis.plan_quality.orchestrators_used:
                    print(f"       Orch:      {', '.join(analysis.plan_quality.orchestrators_used)}")
                if args.verbose and analysis.plan_quality.safeguards_fired:
                    print(f"       Guards:    {', '.join(analysis.plan_quality.safeguards_fired)}")
                if args.verbose and analysis.self_correction.count > 0:
                    for detail in analysis.self_correction.correction_details[:3]:
                        print(f"       SC [{detail['type']}]: {detail['summary'][:80]}")

                analyses.append(analysis)

            except PromptClientError as e:
                print(f"\r       ERROR:     {e}")
                from prompt_analyzer import PromptAnalysis
                error_analysis = PromptAnalysis(
                    fixture_id=fixture_id,
                    prompt_name=prompt_name,
                    status="error",
                    verdict="ERROR",
                    verdict_reasons=[str(e)],
                )
                analyses.append(error_analysis)

        # Step 5: Generate reports
        print(f"\n[ * ] Generating reports...", end=" ", flush=True)

        summary = PromptReporter.compute_summary(analyses)
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "server_url": args.server,
            "fixtures_file": str(args.fixtures),
            "filter": args.filter,
            "tag": args.tag,
            "profile_tag": args.profile_tag,
            "profile_id": profile_id,
        }

        output_dir = Path(__file__).parent / args.output_dir
        output_dir.mkdir(exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON report
        json_report = PromptReporter.generate_json_report(analyses, summary, metadata)
        json_file = output_dir / f"prompt_test_{timestamp_str}.json"
        with open(json_file, "w") as f:
            json.dump(json_report, f, indent=2)

        # Markdown report
        md_report = PromptReporter.generate_markdown_report(analyses, summary, metadata)
        md_file = output_dir / f"prompt_test_{timestamp_str}.md"
        with open(md_file, "w") as f:
            f.write(md_report)

        print("done")
        print(f"       JSON:     {json_file}")
        print(f"       Markdown: {md_file}")

        # Step 6: Print summary table
        PromptReporter.print_summary_table(analyses, summary)

        # Exit code: 0 if all pass, 1 if any fail/error
        return 0 if summary.failed == 0 and summary.errored == 0 else 1

    except PromptClientError as e:
        print(f"\nERROR: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        return 130


def run_discover_mode(client: PromptClient) -> int:
    """List available MCP prompts and their parameters."""
    print("\nDiscovering available prompts...\n")

    try:
        prompts_by_category = client.discover_prompts()
    except PromptClientError as e:
        print(f"ERROR: {e}")
        return 1

    total = 0
    print("=" * 60)
    print("  Available MCP Prompts")
    print("=" * 60)

    for category, prompts in sorted(prompts_by_category.items()):
        active_prompts = [p for p in prompts if not p.disabled]
        if not active_prompts:
            continue

        print(f"\n  Category: {category}")
        print("  " + "-" * 40)

        for prompt in active_prompts:
            total += 1
            print(f"    {prompt.name}")
            if prompt.description:
                desc = prompt.description[:80]
                print(f"      {desc}")
            if prompt.arguments:
                for arg in prompt.arguments:
                    req = "required" if arg.get("required") else "optional"
                    arg_type = arg.get("type", "string")
                    arg_desc = arg.get("description", "")[:60]
                    print(f"      - {arg['name']} ({arg_type}, {req}): {arg_desc}")

    print(f"\n  Total: {total} prompts across {len(prompts_by_category)} categories")
    print("=" * 60)
    return 0


def load_fixtures(
    fixtures_path: str,
    filter_pattern: str = None,
    tags: list = None,
    default_timeout: int = 180,
) -> list:
    """Load and filter fixtures from JSON file."""
    path = Path(fixtures_path)
    if not path.is_absolute():
        path = Path(__file__).parent / path

    if not path.exists():
        print(f"\nERROR: Fixtures file not found: {path}")
        print("Create it with test case definitions (see mcp_prompt_fixtures.json).")
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)

    fixtures = data.get("fixtures", [])
    defaults = data.get("defaults", {})

    # Apply defaults
    for fixture in fixtures:
        if "timeout_seconds" not in fixture:
            fixture["timeout_seconds"] = defaults.get("timeout_seconds", default_timeout)
        if "expectations" not in fixture:
            fixture["expectations"] = {}
        if (
            defaults.get("expect_zero_self_corrections")
            and "max_self_corrections" not in fixture["expectations"]
        ):
            fixture["expectations"]["max_self_corrections"] = 0

    # Apply substring filter
    if filter_pattern:
        lower_filter = filter_pattern.lower()
        fixtures = [
            f
            for f in fixtures
            if lower_filter in f["prompt_name"].lower()
            or lower_filter in f["id"].lower()
        ]

    # Apply tag filter
    if tags:
        fixtures = [
            f for f in fixtures if any(tag in f.get("tags", []) for tag in tags)
        ]

    return fixtures


if __name__ == "__main__":
    sys.exit(main())
