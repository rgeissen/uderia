#!/usr/bin/env python3
"""
MCP Tool Performance Test Framework for Uderia Platform.

Tests MCP tools end-to-end via natural language queries that trigger
the planner/executor to select specific tools. Analyzes execution quality
using fusion hardening patterns and generates JSON + Markdown reports.

The test creates real sessions so you can watch executions in the UI.

Usage:
    # Run all fixtures
    python mcp_tool_test.py

    # Discover available tools and their metadata
    python mcp_tool_test.py --discover

    # Generate fixture templates from discovered tools
    python mcp_tool_test.py --discover --generate-fixtures > mcp_tool_fixtures.json

    # Run only specific tools
    python mcp_tool_test.py --filter base_readQuery

    # Run fixtures by tag
    python mcp_tool_test.py --tag database-scope

    # Custom server and credentials
    python mcp_tool_test.py --server http://myserver:5050 --username dev --password devpw
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
        description="MCP Tool Performance Test Framework for Uderia Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mcp_tool_test.py                              # Run all fixtures
  python mcp_tool_test.py --discover                   # List available tools
  python mcp_tool_test.py --discover --generate-fixtures  # Generate fixture templates
  python mcp_tool_test.py --filter base                # Run base_ tools only
  python mcp_tool_test.py --tag column-scope           # Run by tag
  python mcp_tool_test.py --profile-tag OPTIM          # Use specific profile
  python mcp_tool_test.py --verbose                    # Show event details
        """,
    )
    parser.add_argument("--server", default="http://localhost:5050", help="Uderia server URL")
    parser.add_argument("--username", default="admin", help="Username for authentication")
    parser.add_argument("--password", default="admin", help="Password for authentication")
    parser.add_argument("--fixtures", default="mcp_tool_fixtures.json", help="Path to fixtures JSON file")
    parser.add_argument("--output-dir", default="results", help="Output directory for reports")
    parser.add_argument("--filter", default=None, help="Substring filter on expected_tool or fixture id")
    parser.add_argument("--tag", action="append", default=None, help="Filter by tag (repeatable)")
    parser.add_argument("--timeout", type=int, default=180, help="Default timeout in seconds")
    parser.add_argument("--profile-tag", default="OPTIM", help="Profile tag (tool_enabled or llm_only with MCP tools)")
    parser.add_argument("--discover", action="store_true", help="List available tools, then exit")
    parser.add_argument("--generate-fixtures", action="store_true", help="Generate fixture templates (use with --discover)")
    parser.add_argument("--verbose", action="store_true", help="Show execution event details")
    args = parser.parse_args()

    client = PromptClient(base_url=args.server)

    # When generating fixtures, all status goes to stderr so stdout is clean JSON
    log_out = sys.stderr if args.generate_fixtures else sys.stdout

    try:
        # Step 1: Authenticate
        print(f"\n[ 1 ] Authenticating with {args.server}...", end=" ", flush=True, file=log_out)
        client.authenticate(args.username, args.password)
        print("done", file=log_out)

        # Step 2: Discovery mode
        if args.discover:
            if args.generate_fixtures:
                return run_generate_fixtures_mode(client)
            else:
                return run_discover_mode(client)

        # Step 3: Resolve profile and detect execution mode
        print(f"[ 2 ] Resolving profile @{args.profile_tag}...", end=" ", flush=True)
        profile_details = client.get_profile_details(args.profile_tag)
        if not profile_details:
            print(f"FAILED - profile @{args.profile_tag} not found")
            print("\nERROR: Profile not found. Use a tool_enabled or llm_only (with MCP tools) profile.")
            return 1
        profile_id = profile_details["id"]
        profile_type = profile_details.get("profile_type", "tool_enabled")
        use_mcp_tools = profile_details.get("useMcpTools", False)

        # Determine execution mode
        if profile_type == "tool_enabled":
            exec_mode = "tool_enabled"
        elif profile_type == "llm_only" and use_mcp_tools:
            exec_mode = "conversation"
        elif profile_type == "llm_only":
            print(f"FAILED - @{args.profile_tag} is llm_only without MCP tools")
            print("\nERROR: Profile must have useMcpTools=true for tool testing.")
            return 1
        else:
            print(f"FAILED - @{args.profile_tag} is {profile_type} (not supported)")
            print("\nERROR: Use a tool_enabled or llm_only (with MCP tools) profile.")
            return 1

        print(f"done ({profile_id[:8]}... | mode: {exec_mode})")

        # Step 4: Load fixtures
        print(f"[ 3 ] Loading fixtures...", end=" ", flush=True)
        fixtures = load_fixtures(args.fixtures, args.filter, args.tag, args.timeout)
        if not fixtures:
            print("no fixtures match filter")
            return 0
        print(f"done ({len(fixtures)} fixture{'s' if len(fixtures) != 1 else ''})")

        # Step 5: Execute each fixture
        analyzer = PromptAnalyzer()
        analyses = []

        for i, fixture in enumerate(fixtures, 1):
            fixture_id = fixture["id"]
            query = fixture["query"]
            expected_tool = fixture.get("expected_tool", "N/A")
            timeout = fixture.get("timeout_seconds", args.timeout)

            print(f"\n[{i:2d}/{len(fixtures)}] {expected_tool} ({fixture_id})")
            print(f"       Query:     {query[:70]}{'...' if len(query) > 70 else ''}")

            try:
                # Create session for this fixture (visible in UI)
                session_id = client.create_session()
                print(f"       Session:   {session_id[:12]}...")

                # Submit natural language query
                task_id = client.submit_query(
                    session_id=session_id,
                    query=query,
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

                # Enrich result with session execution trace (captures orchestrator-wrapped tools)
                try:
                    session_data = client.get_session(session_id)
                    result.session_data = session_data
                except Exception:
                    result.session_data = None

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
                if args.verbose:
                    print(f"       Mode:      {analysis.execution_mode}")
                if args.verbose and analysis.plan_quality.tools_invoked:
                    print(f"       Tools:     {', '.join(analysis.plan_quality.tools_invoked)}")
                if args.verbose and analysis.plan_quality.orchestrators_used:
                    print(f"       Orch:      {', '.join(analysis.plan_quality.orchestrators_used)}")
                if args.verbose and analysis.plan_quality.safeguards_fired:
                    print(f"       Guards:    {', '.join(analysis.plan_quality.safeguards_fired)}")
                if args.verbose and analysis.plan_quality.rewrite_passes_fired:
                    print(f"       Rewrites:  {', '.join(analysis.plan_quality.rewrite_passes_fired)}")
                if args.verbose and analysis.self_correction.count > 0:
                    for detail in analysis.self_correction.correction_details[:3]:
                        print(f"       SC [{detail['type']}]: {detail['summary'][:80]}")

                analyses.append(analysis)

            except PromptClientError as e:
                print(f"\r       ERROR:     {e}")
                from prompt_analyzer import PromptAnalysis
                error_analysis = PromptAnalysis(
                    fixture_id=fixture_id,
                    prompt_name=expected_tool,
                    status="error",
                    verdict="ERROR",
                    verdict_reasons=[str(e)],
                )
                analyses.append(error_analysis)

        # Step 6: Generate reports
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
            "profile_type": profile_type,
            "execution_mode": exec_mode,
            "test_type": "mcp_tool",
        }

        output_dir = Path(__file__).parent / args.output_dir
        output_dir.mkdir(exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON report
        json_report = PromptReporter.generate_json_report(analyses, summary, metadata)
        json_file = output_dir / f"tool_test_{timestamp_str}.json"
        with open(json_file, "w") as f:
            json.dump(json_report, f, indent=2)

        # Markdown report
        md_report = PromptReporter.generate_markdown_report(analyses, summary, metadata)
        md_file = output_dir / f"tool_test_{timestamp_str}.md"
        with open(md_file, "w") as f:
            f.write(md_report)

        print("done")
        print(f"       JSON:     {json_file}")
        print(f"       Markdown: {md_file}")

        # Step 7: Print summary table
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
    """List available MCP tools and their metadata."""
    print("\nDiscovering available tools...\n")

    try:
        tools_by_category = client.discover_tools()
    except PromptClientError as e:
        print(f"ERROR: {e}")
        return 1

    total = 0
    print("=" * 80)
    print("  Available MCP Tools")
    print("=" * 80)

    for category, tools in sorted(tools_by_category.items()):
        active_tools = [t for t in tools if not t.disabled]
        if not active_tools:
            continue

        print(f"\n  Category: {category}")
        print("  " + "-" * 60)

        for tool in active_tools:
            total += 1
            print(f"    {tool.name} (scope: {tool.scope})")
            if tool.description:
                desc = tool.description[:80]
                print(f"      {desc}")
            if tool.arguments:
                for arg in tool.arguments:
                    req = "required" if arg.get("required") else "optional"
                    arg_type = arg.get("type", "string")
                    arg_desc = arg.get("description", "")[:60]
                    print(f"      - {arg['name']} ({arg_type}, {req}): {arg_desc}")

    print(f"\n  Total: {total} tools across {len(tools_by_category)} categories")
    print("=" * 80)
    return 0


def run_generate_fixtures_mode(client: PromptClient) -> int:
    """Generate fixture templates from discovered tools."""
    print("\nGenerating fixture templates from discovered tools...\n", file=sys.stderr)

    try:
        tools_by_category = client.discover_tools()
    except PromptClientError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    fixtures = []

    for category, tools in sorted(tools_by_category.items()):
        for tool in tools:
            if tool.disabled:
                continue

            # Skip TDA_ client-side tools (infrastructure, not MCP server tools)
            if tool.name.startswith("TDA_"):
                continue

            fixture_id = f"{tool.name}_fixture"
            query_hint = _generate_query_hint(tool)

            # Extract expected argument placeholders
            expected_args = {}
            for arg in tool.arguments:
                if arg.get("required"):
                    arg_name = arg["name"]
                    if "database" in arg_name.lower():
                        expected_args[arg_name] = "YOUR_DATABASE_NAME"
                    elif "table" in arg_name.lower() or "object" in arg_name.lower():
                        expected_args[arg_name] = "YOUR_TABLE_NAME"
                    elif "column" in arg_name.lower():
                        expected_args[arg_name] = "YOUR_COLUMN_NAME"
                    elif "sql" in arg_name.lower():
                        expected_args[arg_name] = "YOUR_SQL_QUERY"
                    elif "date" in arg_name.lower():
                        expected_args[arg_name] = "YOUR_DATE"
                    else:
                        expected_args[arg_name] = f"YOUR_{arg_name.upper()}"

            # Determine tags
            tags = []
            if tool.scope != "global":
                tags.append(f"{tool.scope}-scope")
            # Add prefix-based category tag
            prefix = tool.name.split("_")[0] if "_" in tool.name else tool.name
            tags.append(prefix)

            expectations = {
                "max_self_corrections": 0,
                "expect_status": "complete",
                "expect_final_report": True,
            }

            if tool.scope == "column":
                expectations["expect_orchestrator"] = "column_iteration"

            fixture = {
                "id": fixture_id,
                "description": f"Test {tool.name} - {(tool.description or '')[:60]}",
                "query": query_hint,
                "expected_tool": tool.name,
                "expected_tool_args": expected_args,
                "tags": tags,
                "expectations": expectations,
            }
            fixtures.append(fixture)

    output = {
        "$schema_version": "1.0",
        "description": "Auto-generated MCP tool test fixtures. UPDATE query strings and argument values for your environment.",
        "defaults": {
            "timeout_seconds": 180,
            "expect_zero_self_corrections": True,
        },
        "fixtures": fixtures,
    }

    # JSON to stdout for redirection
    print(json.dumps(output, indent=2))

    print(f"\n# Generated {len(fixtures)} fixture templates", file=sys.stderr)
    print("# Review and update query strings and argument values before running tests", file=sys.stderr)

    return 0


def _generate_query_hint(tool) -> str:
    """Generate a natural language query hint for a tool based on its scope and category."""
    name = tool.name
    desc = tool.description or name

    # Derive action from description or name
    if name.startswith("base_"):
        action = "data operation"
    elif name.startswith("qlty_"):
        action = "quality analysis"
    elif name.startswith("dba_"):
        action = "system monitoring"
    else:
        action = "operation"

    # Generate scope-appropriate query template
    if tool.scope == "column":
        return f"Analyze the [COLUMN_NAME] column in [TABLE_NAME] table of [DATABASE_NAME] database - {desc[:60]}"
    elif tool.scope == "table":
        return f"Show {action} for [TABLE_NAME] table in [DATABASE_NAME] database - {desc[:60]}"
    elif tool.scope == "database":
        return f"Show {action} for [DATABASE_NAME] database - {desc[:60]}"
    else:
        return f"Perform {action}: {desc[:80]}"


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
        print("Create it with: python mcp_tool_test.py --discover --generate-fixtures > mcp_tool_fixtures.json")
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)

    fixtures = data.get("fixtures", [])
    defaults = data.get("defaults", {})

    # Filter out disabled fixtures
    fixtures = [f for f in fixtures if not f.get("disabled", False)]

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
            if lower_filter in f.get("expected_tool", "").lower()
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
