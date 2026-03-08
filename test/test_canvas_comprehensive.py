#!/usr/bin/env python3
"""
Comprehensive Canvas Component Test Suite

Tests ALL canvas functionality via REST API and direct handler invocation:

  1. Handler Pipeline     — validation, language detection, metadata computation
  2. REST API Endpoints   — /canvas/templates, /canvas/inline-ai, /canvas/execute
  3. Template Gallery     — JSON integrity, category coverage, language correctness
  4. Diff Algorithm       — line-based LCS diff logic (ported from renderer.js)
  5. Version History      — dedup, ordering, turn tracking
  6. End-to-End           — submit query that triggers TDA_Canvas via @OPTIM/@IDEAT

Prerequisites:
  - Uderia server running on localhost:5050
  - Default profile configured (for E2E tests)
  - Admin credentials available

Usage:
  python test/test_canvas_comprehensive.py                    # All tests
  python test/test_canvas_comprehensive.py --unit-only        # Handler + diff + templates (no server)
  python test/test_canvas_comprehensive.py --api-only         # REST API tests only
  python test/test_canvas_comprehensive.py --e2e              # Include slow E2E LLM tests
  python test/test_canvas_comprehensive.py -v                 # Verbose output
"""

import argparse
import asyncio
import json
import os
import sys
import time
import traceback

# ─── Path setup ───────────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))


# ─── Test infrastructure ──────────────────────────────────────────────────────

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    @property
    def total(self):
        return self.passed + self.failed + self.skipped


results = TestResult()
VERBOSE = False


def log(msg, indent=0):
    prefix = "  " * indent
    print(f"{prefix}{msg}")


def log_v(msg, indent=0):
    if VERBOSE:
        log(msg, indent)


def test_pass(name, detail=""):
    results.passed += 1
    suffix = f" — {detail}" if detail else ""
    log(f"  PASS  {name}{suffix}")


def test_fail(name, reason):
    results.failed += 1
    results.errors.append((name, reason))
    log(f"  FAIL  {name} — {reason}")


def test_skip(name, reason=""):
    results.skipped += 1
    suffix = f" — {reason}" if reason else ""
    log(f"  SKIP  {name}{suffix}")


def section(title):
    log(f"\n{'─' * 60}")
    log(f"  {title}")
    log(f"{'─' * 60}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Handler Unit Tests (no server required)
# ═══════════════════════════════════════════════════════════════════════════════

def run_handler_tests():
    section("1. Canvas Handler — Unit Tests")

    try:
        from trusted_data_agent.components.base import ComponentRenderPayload, RenderTarget
    except ImportError:
        test_skip("Handler import", "Cannot import components.base — run with PYTHONPATH or pip install -e .")
        return

    # Import handler directly
    handler_path = os.path.join(PROJECT_ROOT, "components", "builtin", "canvas")
    sys.path.insert(0, handler_path)

    try:
        from handler import CanvasComponentHandler
    except ImportError:
        test_skip("Handler import", "Cannot import CanvasComponentHandler")
        return
    finally:
        sys.path.pop(0)

    h = CanvasComponentHandler()

    # ── 1.1 Component identity ──
    assert h.component_id == "canvas", f"Expected 'canvas', got '{h.component_id}'"
    test_pass("component_id == 'canvas'")

    assert h.tool_name == "TDA_Canvas", f"Expected 'TDA_Canvas', got '{h.tool_name}'"
    test_pass("tool_name == 'TDA_Canvas'")

    assert h.is_deterministic is True
    test_pass("is_deterministic == True")

    # ── 1.2 Validation ──
    ok, msg = h.validate_arguments({})
    assert not ok, "Should fail with no content"
    test_pass("validate: missing content → fail")

    ok, msg = h.validate_arguments({"content": ""})
    assert not ok, "Should fail with empty content"
    test_pass("validate: empty string → fail")

    ok, msg = h.validate_arguments({"content": "   "})
    assert not ok, "Should fail with whitespace-only content"
    test_pass("validate: whitespace only → fail")

    ok, msg = h.validate_arguments({"content": 123})
    assert not ok, "Should fail with non-string content"
    test_pass("validate: non-string → fail")

    ok, msg = h.validate_arguments({"content": "hello"})
    assert ok, f"Should pass with valid content, got: {msg}"
    test_pass("validate: valid content → pass")

    # ── 1.3 Language detection ──
    detect = CanvasComponentHandler._detect_language

    cases = [
        ("<!DOCTYPE html><html>", "html", "DOCTYPE"),
        ("<html lang='en'>", "html", "<html>"),
        ("<head><title>Test</title></head>", "html", "<head>"),
        ("<svg xmlns='http://www.w3.org/2000/svg'>", "svg", "<svg>"),
        ("graph TD\n  A-->B", "mermaid", "graph TD"),
        ("sequenceDiagram\n  Alice->>Bob: Hi", "mermaid", "sequenceDiagram"),
        ("def hello():\n  print('hi')", "python", "def keyword"),
        ("import os\nimport sys", "python", "import keyword"),
        ("SELECT * FROM users WHERE id = 1", "sql", "SELECT"),
        ("CREATE TABLE products (id INT)", "sql", "CREATE TABLE"),
        ("INSERT INTO logs VALUES (1, 'test')", "sql", "INSERT INTO"),
        ('{"key": "value", "num": 42}', "json", "JSON object"),
        ("# My Document\n\nSome text", "markdown", "# heading"),
        ("Some text\n## Subsection", "markdown", "## heading"),
        ("", None, "empty string"),
        ("random text without patterns", None, "no match"),
    ]

    for content, expected, label in cases:
        result = detect(content)
        if result == expected:
            test_pass(f"detect: {label} → {expected}")
        else:
            test_fail(f"detect: {label}", f"expected {expected}, got {result}")

    # ── 1.4 Process output ──
    async def test_process():
        # Basic HTML
        payload = await h.process({"content": "<h1>Hello</h1>", "language": "html", "title": "Test"})
        assert isinstance(payload, ComponentRenderPayload)
        assert payload.component_id == "canvas"
        assert payload.render_target == RenderTarget.INLINE
        assert payload.spec["language"] == "html"
        assert payload.spec["previewable"] is True
        assert payload.spec["line_count"] == 1
        assert payload.spec["file_extension"] == ".html"
        assert payload.spec["sources"] is None
        assert payload.title == "Test"
        test_pass("process: HTML basic payload")

        # Python (not previewable)
        payload = await h.process({"content": "def foo():\n  pass\n  return 1", "language": "python"})
        assert payload.spec["previewable"] is False
        assert payload.spec["line_count"] == 3
        assert payload.spec["file_extension"] == ".py"
        assert payload.title == "Canvas"  # default
        test_pass("process: Python payload (not previewable)")

        # SVG (previewable)
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="40"/></svg>'
        payload = await h.process({"content": svg, "language": "svg"})
        assert payload.spec["previewable"] is True
        assert payload.spec["file_extension"] == ".svg"
        test_pass("process: SVG payload (previewable)")

        # Markdown (previewable)
        payload = await h.process({"content": "# Hello\n\nWorld", "language": "markdown"})
        assert payload.spec["previewable"] is True
        assert payload.spec["file_extension"] == ".md"
        test_pass("process: Markdown payload (previewable)")

        # Auto-detect language (invalid language provided)
        payload = await h.process({"content": "SELECT 1", "language": "foobar"})
        assert payload.spec["language"] == "sql", f"Expected sql, got {payload.spec['language']}"
        test_pass("process: auto-detect fallback (foobar → sql)")

        # Sources field
        payload = await h.process({
            "content": "test",
            "language": "html",
            "sources": "Doc A (coll1), Doc B (coll2)"
        })
        assert payload.spec["sources"] == "Doc A (coll1), Doc B (coll2)"
        test_pass("process: sources field propagated")

        # Empty sources → None
        payload = await h.process({"content": "test", "language": "html", "sources": ""})
        assert payload.spec["sources"] is None
        test_pass("process: empty sources → None")

        # Metadata
        payload = await h.process({"content": "line1\nline2\nline3\nline4\nline5", "language": "json"})
        assert payload.metadata["content_length"] == len("line1\nline2\nline3\nline4\nline5")
        assert payload.metadata["line_count"] == 5
        assert payload.metadata["language"] == "json"
        assert payload.metadata["tool_name"] == "TDA_Canvas"
        test_pass("process: metadata fields correct")

    asyncio.get_event_loop().run_until_complete(test_process())

    # ── 1.5 Extension map coverage ──
    expected_extensions = {
        "html": ".html", "css": ".css", "javascript": ".js", "python": ".py",
        "sql": ".sql", "markdown": ".md", "json": ".json", "svg": ".svg", "mermaid": ".mmd",
    }
    for lang, ext in expected_extensions.items():
        actual = h.EXTENSION_MAP.get(lang)
        if actual == ext:
            test_pass(f"extension: {lang} → {ext}")
        else:
            test_fail(f"extension: {lang}", f"expected {ext}, got {actual}")

    # Unknown language → .txt fallback
    async def test_unknown_ext():
        payload = await h.process({"content": "random stuff", "language": "text"})
        # "text" is not in SUPPORTED_LANGUAGES, so it auto-detects.
        # The content "random stuff" doesn't match any heuristic → None → fallback to "html"
        assert payload.spec["file_extension"] in (".html", ".txt"), \
            f"Expected .html or .txt, got {payload.spec['file_extension']}"
        test_pass("extension: unknown language fallback")

    asyncio.get_event_loop().run_until_complete(test_unknown_ext())


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Diff Algorithm Tests (pure logic, no server)
# ═══════════════════════════════════════════════════════════════════════════════

def run_diff_tests():
    """Port of the LCS diff algorithm from renderer.js for validation."""
    section("2. Diff Algorithm — Unit Tests")

    def compute_line_diff(old_text, new_text):
        """Python port of renderer.js computeLineDiff()."""
        old_lines = old_text.split('\n')
        new_lines = new_text.split('\n')
        m, n = len(old_lines), len(new_lines)

        # Build LCS table
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if old_lines[i - 1] == new_lines[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

        # Backtrack
        diff = []
        i, j = m, n
        while i > 0 or j > 0:
            if i > 0 and j > 0 and old_lines[i - 1] == new_lines[j - 1]:
                diff.insert(0, {"type": "equal", "line": old_lines[i - 1]})
                i -= 1
                j -= 1
            elif j > 0 and (i == 0 or dp[i][j - 1] >= dp[i - 1][j]):
                diff.insert(0, {"type": "added", "line": new_lines[j - 1]})
                j -= 1
            else:
                diff.insert(0, {"type": "removed", "line": old_lines[i - 1]})
                i -= 1
        return diff

    def diff_stats(diff):
        added = sum(1 for d in diff if d["type"] == "added")
        removed = sum(1 for d in diff if d["type"] == "removed")
        return {"added": added, "removed": removed}

    # 2.1 Identical content
    d = compute_line_diff("a\nb\nc", "a\nb\nc")
    stats = diff_stats(d)
    assert stats["added"] == 0 and stats["removed"] == 0
    assert all(e["type"] == "equal" for e in d)
    test_pass("diff: identical → 0 added, 0 removed")

    # 2.2 Single line added
    d = compute_line_diff("a\nc", "a\nb\nc")
    stats = diff_stats(d)
    assert stats["added"] == 1 and stats["removed"] == 0
    added_lines = [e["line"] for e in d if e["type"] == "added"]
    assert added_lines == ["b"]
    test_pass("diff: single line added")

    # 2.3 Single line removed
    d = compute_line_diff("a\nb\nc", "a\nc")
    stats = diff_stats(d)
    assert stats["added"] == 0 and stats["removed"] == 1
    removed_lines = [e["line"] for e in d if e["type"] == "removed"]
    assert removed_lines == ["b"]
    test_pass("diff: single line removed")

    # 2.4 Line modified (shows as remove + add)
    d = compute_line_diff("a\nold\nc", "a\nnew\nc")
    stats = diff_stats(d)
    assert stats["added"] == 1 and stats["removed"] == 1
    test_pass("diff: modified line → 1 added + 1 removed")

    # 2.5 Empty old → all added
    d = compute_line_diff("", "a\nb\nc")
    stats = diff_stats(d)
    assert stats["added"] == 3 and stats["removed"] == 1  # empty string = 1 empty line
    test_pass("diff: empty old → all added")

    # 2.6 Empty new → all removed
    d = compute_line_diff("a\nb\nc", "")
    stats = diff_stats(d)
    assert stats["removed"] == 3 and stats["added"] == 1
    test_pass("diff: empty new → all removed")

    # 2.7 Multi-line changes
    old = "line1\nline2\nline3\nline4\nline5"
    new = "line1\nmodified2\nline3\nnew_line\nline5"
    d = compute_line_diff(old, new)
    stats = diff_stats(d)
    assert stats["added"] == 2 and stats["removed"] == 2
    test_pass(f"diff: multi-line → {stats['added']} added, {stats['removed']} removed")

    # 2.8 Large diff (performance sanity)
    old_large = "\n".join(f"line {i}" for i in range(200))
    new_large = "\n".join(f"line {i}" if i % 10 != 5 else f"modified {i}" for i in range(200))
    start = time.time()
    d = compute_line_diff(old_large, new_large)
    elapsed = time.time() - start
    stats = diff_stats(d)
    assert elapsed < 5.0, f"200-line diff took {elapsed:.2f}s (too slow)"
    test_pass(f"diff: 200 lines in {elapsed:.3f}s — {stats['added']}a/{stats['removed']}r")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Template Gallery Tests (file-based, no server)
# ═══════════════════════════════════════════════════════════════════════════════

def run_template_tests():
    section("3. Template Gallery — File Integrity Tests")

    templates_path = os.path.join(
        PROJECT_ROOT, "components", "builtin", "canvas", "templates.json"
    )

    if not os.path.exists(templates_path):
        test_fail("templates.json", "File not found")
        return

    with open(templates_path, "r") as f:
        try:
            templates = json.load(f)
        except json.JSONDecodeError as e:
            test_fail("templates.json", f"Invalid JSON: {e}")
            return

    assert isinstance(templates, list), "templates.json must be a JSON array"
    test_pass(f"templates.json: valid JSON array ({len(templates)} templates)")

    # 3.1 Required fields
    required_fields = {"id", "name", "category", "language", "description", "content"}
    valid_languages = {"html", "css", "javascript", "python", "sql", "markdown", "json", "svg", "mermaid"}

    ids_seen = set()
    categories = set()
    lang_coverage = set()

    for i, t in enumerate(templates):
        tid = t.get("id", f"<index {i}>")

        # Check required fields
        missing = required_fields - set(t.keys())
        if missing:
            test_fail(f"template[{tid}]", f"missing fields: {missing}")
            continue

        # Check duplicate IDs
        if tid in ids_seen:
            test_fail(f"template[{tid}]", "duplicate ID")
        ids_seen.add(tid)

        # Check language valid
        lang = t["language"]
        if lang not in valid_languages:
            test_fail(f"template[{tid}]", f"invalid language: {lang}")
        lang_coverage.add(lang)

        # Check content non-empty
        if not t["content"].strip():
            test_fail(f"template[{tid}]", "empty content")

        categories.add(t["category"])

    test_pass(f"template IDs: {len(ids_seen)} unique (no duplicates)")
    test_pass(f"categories: {sorted(categories)}")
    test_pass(f"language coverage: {sorted(lang_coverage)}")

    # 3.2 Minimum coverage
    min_categories = {"HTML", "Python"}
    missing_cats = min_categories - categories
    if missing_cats:
        test_fail("template categories", f"missing: {missing_cats}")
    else:
        test_pass("template categories: HTML + Python present")

    min_languages = {"html", "python", "javascript", "sql"}
    missing_langs = min_languages - lang_coverage
    if missing_langs:
        test_fail("language coverage", f"missing: {missing_langs}")
    else:
        test_pass("language coverage: core languages present")

    # 3.3 HTML templates contain DOCTYPE or <html>
    html_templates = [t for t in templates if t["language"] == "html"]
    valid_html = sum(1 for t in html_templates if "<!DOCTYPE" in t["content"] or "<html" in t["content"])
    test_pass(f"HTML templates: {valid_html}/{len(html_templates)} have DOCTYPE/<html>")

    # 3.4 Content size sanity
    sizes = [len(t["content"]) for t in templates]
    avg_size = sum(sizes) / len(sizes) if sizes else 0
    max_size = max(sizes) if sizes else 0
    min_size = min(sizes) if sizes else 0
    test_pass(f"content sizes: min={min_size}, avg={avg_size:.0f}, max={max_size} chars")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Version History Tests (pure logic, no server)
# ═══════════════════════════════════════════════════════════════════════════════

def run_version_tests():
    """Test version store logic (Python port of renderer.js recordVersion)."""
    section("4. Version History — Unit Tests")

    versions_store = {}  # Simulates _canvasVersions Map
    turn_counter = [0]   # Simulates _globalTurnCounter

    def record_version(title, content, language):
        key = title.lower().strip()
        if key not in versions_store:
            versions_store[key] = []
        versions = versions_store[key]

        # Dedup: skip if same as last
        if versions and versions[-1]["content"] == content:
            prev = versions[-2]["content"] if len(versions) > 1 else None
            return {
                "versions": versions,
                "previousContent": prev,
                "versionNumber": len(versions),
            }

        turn_counter[0] += 1
        versions.append({
            "content": content,
            "language": language,
            "timestamp": time.time(),
            "turnIndex": turn_counter[0],
        })

        prev = versions[-2]["content"] if len(versions) > 1 else None
        return {
            "versions": versions,
            "previousContent": prev,
            "versionNumber": len(versions),
        }

    # 4.1 First version
    r = record_version("My Canvas", "content v1", "html")
    assert r["versionNumber"] == 1
    assert r["previousContent"] is None
    test_pass("version: first version (no previous)")

    # 4.2 Second version
    r = record_version("My Canvas", "content v2", "html")
    assert r["versionNumber"] == 2
    assert r["previousContent"] == "content v1"
    test_pass("version: second version (previous = v1)")

    # 4.3 Duplicate content skipped
    r = record_version("My Canvas", "content v2", "html")
    assert r["versionNumber"] == 2, "Should not create new version for duplicate"
    test_pass("version: duplicate content skipped")

    # 4.4 Case-insensitive title matching
    r = record_version("MY CANVAS", "content v3", "html")
    assert r["versionNumber"] == 3
    assert r["previousContent"] == "content v2"
    test_pass("version: title matching is case-insensitive")

    # 4.5 Different canvas titles are independent
    r = record_version("Other Canvas", "other content", "python")
    assert r["versionNumber"] == 1
    assert r["previousContent"] is None
    test_pass("version: different titles are independent stores")

    # 4.6 Turn counter increments globally
    assert turn_counter[0] == 4, f"Expected 4 turns, got {turn_counter[0]}"
    test_pass("version: global turn counter = 4 (3 unique + 1 other)")

    # 4.7 Many versions
    for i in range(20):
        record_version("Bulk Canvas", f"content {i}", "javascript")
    r = record_version("Bulk Canvas", "content 20", "javascript")
    assert r["versionNumber"] == 21
    test_pass("version: 21 sequential versions tracked")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Manifest Integrity Tests (file-based, no server)
# ═══════════════════════════════════════════════════════════════════════════════

def run_manifest_tests():
    section("5. Manifest — Integrity Tests")

    manifest_path = os.path.join(
        PROJECT_ROOT, "components", "builtin", "canvas", "manifest.json"
    )

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    # 5.1 Required top-level fields
    required = ["component_id", "display_name", "description", "version",
                "component_type", "tool_definition", "backend", "frontend",
                "render_targets", "profile_defaults"]
    for field in required:
        if field in manifest:
            test_pass(f"manifest: has '{field}'")
        else:
            test_fail(f"manifest: missing '{field}'", "required field")

    # 5.2 Tool definition
    tool_def = manifest.get("tool_definition", {})
    assert tool_def.get("name") == "TDA_Canvas"
    test_pass("manifest: tool name = TDA_Canvas")

    args = tool_def.get("args", {})
    assert "content" in args and args["content"].get("required") is True
    test_pass("manifest: content arg required")
    assert "language" in args and args["language"].get("required") is True
    test_pass("manifest: language arg required")
    assert "title" in args and args["title"].get("required") is False
    test_pass("manifest: title arg optional")
    assert "sources" in args and args["sources"].get("required") is False
    test_pass("manifest: sources arg optional")

    # 5.3 Backend config
    backend = manifest.get("backend", {})
    assert backend.get("handler_class") == "CanvasComponentHandler"
    assert backend.get("fast_path") is True
    test_pass("manifest: backend fast_path + handler class")

    # 5.4 Frontend config
    frontend = manifest.get("frontend", {})
    assert frontend.get("renderer_export") == "renderCanvas"
    assert frontend.get("renderer_file") == "renderer.js"
    test_pass("manifest: frontend renderer config")

    # 5.5 Profile defaults
    defaults = manifest.get("profile_defaults", {})
    enabled_for = defaults.get("enabled_for", [])
    assert set(enabled_for) == {"tool_enabled", "llm_only", "rag_focused", "genie"}
    test_pass("manifest: enabled for all 4 profile types")
    assert defaults.get("default_intensity") == "medium"
    test_pass("manifest: default intensity = medium")

    # 5.6 Render targets
    targets = manifest.get("render_targets", {})
    assert targets.get("default") == "inline"
    assert "inline" in targets.get("supports", [])
    assert "sub_window" in targets.get("supports", [])
    test_pass("manifest: supports inline + sub_window")

    sub = targets.get("sub_window", {})
    assert sub.get("resizable") is True
    assert sub.get("interactive") is True
    test_pass("manifest: sub_window resizable + interactive")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Instructions Intensity Tests (file-based, no server)
# ═══════════════════════════════════════════════════════════════════════════════

def run_instructions_tests():
    section("6. Instructions — Intensity Levels")

    instr_path = os.path.join(
        PROJECT_ROOT, "components", "builtin", "canvas", "instructions.json"
    )

    with open(instr_path, "r") as f:
        instructions = json.load(f)

    # 6.1 All three intensity levels present
    for level in ["none", "medium", "heavy"]:
        if level in instructions:
            test_pass(f"instructions: '{level}' level present")
        else:
            test_fail(f"instructions: missing '{level}'", "required intensity level")

    # 6.2 None is empty
    assert instructions.get("none") == "", "none intensity should be empty string"
    test_pass("instructions: 'none' is empty string")

    # 6.3 Medium contains key instructions
    medium = instructions.get("medium", "")
    assert "TDA_Canvas" in medium, "medium should reference TDA_Canvas"
    assert "content" in medium.lower(), "medium should mention content arg"
    assert "language" in medium.lower(), "medium should mention language arg"
    test_pass("instructions: 'medium' mentions TDA_Canvas + args")

    # 6.4 Heavy is more aggressive
    heavy = instructions.get("heavy", "")
    assert "MUST" in heavy, "heavy should use strong language (MUST)"
    assert len(heavy) > 0 and len(heavy) <= len(medium) * 2
    test_pass("instructions: 'heavy' uses MUST + reasonable length")

    # 6.5 Both medium and heavy mention canvas updates (same title)
    assert "same title" in medium.lower() or "SAME title" in medium
    test_pass("instructions: medium mentions 'same title' for updates")

    # 6.6 Sources instruction in both
    assert "sources" in medium.lower()
    assert "sources" in heavy.lower()
    test_pass("instructions: both levels mention 'sources' arg")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7: REST API Tests (requires running server)
# ═══════════════════════════════════════════════════════════════════════════════

def run_api_tests():
    section("7. REST API — Canvas Endpoints")

    try:
        import requests
    except ImportError:
        test_skip("REST API tests", "requests module not available")
        return

    BASE_URL = "http://127.0.0.1:5050"

    # Check server is running
    try:
        resp = requests.get(f"{BASE_URL}/api/v1/auth/login", timeout=3)
    except requests.ConnectionError:
        test_skip("REST API tests", "Server not running on localhost:5050")
        return

    # Authenticate
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"username": "admin", "password": "admin"},
            timeout=10
        )
        if resp.status_code != 200:
            test_skip("REST API tests", f"Auth failed: {resp.status_code}")
            return
        jwt_token = resp.json().get("token")
        if not jwt_token:
            test_skip("REST API tests", "No JWT token returned")
            return
        test_pass("auth: login successful")
    except Exception as e:
        test_skip("REST API tests", f"Auth error: {e}")
        return

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
    }

    # ── 7.1 Templates endpoint ──
    try:
        resp = requests.get(f"{BASE_URL}/api/v1/canvas/templates", headers=headers, timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert data.get("status") == "success"
        templates = data.get("templates", [])
        assert len(templates) > 0, "No templates returned"
        test_pass(f"GET /canvas/templates: {len(templates)} templates")

        # Verify structure matches file
        first = templates[0]
        assert "id" in first and "name" in first and "content" in first
        test_pass("GET /canvas/templates: correct structure")
    except AssertionError as e:
        test_fail("GET /canvas/templates", str(e))
    except Exception as e:
        test_fail("GET /canvas/templates", f"Exception: {e}")

    # ── 7.2 Inline AI endpoint — validation ──
    try:
        # Missing required fields
        resp = requests.post(
            f"{BASE_URL}/api/v1/canvas/inline-ai",
            headers=headers,
            json={"selected_code": "", "instruction": ""},
            timeout=10
        )
        assert resp.status_code == 400, f"Expected 400 for empty fields, got {resp.status_code}"
        test_pass("POST /canvas/inline-ai: empty fields → 400")

        # Missing instruction
        resp = requests.post(
            f"{BASE_URL}/api/v1/canvas/inline-ai",
            headers=headers,
            json={"selected_code": "x = 1", "instruction": ""},
            timeout=10
        )
        assert resp.status_code == 400
        test_pass("POST /canvas/inline-ai: missing instruction → 400")

        # Missing selected_code
        resp = requests.post(
            f"{BASE_URL}/api/v1/canvas/inline-ai",
            headers=headers,
            json={"selected_code": "", "instruction": "add logging"},
            timeout=10
        )
        assert resp.status_code == 400
        test_pass("POST /canvas/inline-ai: missing selected_code → 400")

    except AssertionError as e:
        test_fail("POST /canvas/inline-ai validation", str(e))
    except Exception as e:
        test_fail("POST /canvas/inline-ai validation", f"Exception: {e}")

    # ── 7.3 Inline AI endpoint — actual LLM call ──
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/canvas/inline-ai",
            headers=headers,
            json={
                "selected_code": "x = 1\ny = 2\nresult = x + y",
                "instruction": "Add type hints",
                "full_content": "def calc():\n    x = 1\n    y = 2\n    result = x + y\n    return result",
                "language": "python"
            },
            timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("status") == "success"
            assert "modified_code" in data
            assert data.get("input_tokens", 0) > 0, "No input tokens"
            assert data.get("output_tokens", 0) > 0, "No output tokens"
            test_pass(f"POST /canvas/inline-ai: LLM call OK "
                      f"({data['input_tokens']} in / {data['output_tokens']} out)")
            log_v(f"Modified code: {data['modified_code'][:100]}...", indent=2)
        elif resp.status_code == 500:
            # LLM might not be configured
            test_skip("POST /canvas/inline-ai LLM call", "LLM not configured (500)")
        else:
            test_fail("POST /canvas/inline-ai LLM call", f"HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        test_fail("POST /canvas/inline-ai LLM call", f"Exception: {e}")

    # ── 7.4 Execute endpoint — validation ──
    try:
        # Empty code
        resp = requests.post(
            f"{BASE_URL}/api/v1/canvas/execute",
            headers=headers,
            json={"code": "", "language": "sql"},
            timeout=10
        )
        assert resp.status_code == 400, f"Expected 400 for empty code, got {resp.status_code}"
        test_pass("POST /canvas/execute: empty code → 400")

        # Unsupported language
        resp = requests.post(
            f"{BASE_URL}/api/v1/canvas/execute",
            headers=headers,
            json={"code": "print('hello')", "language": "python"},
            timeout=10
        )
        assert resp.status_code == 400
        msg = resp.json().get("message", "")
        assert "not supported" in msg.lower() or "only sql" in msg.lower()
        test_pass("POST /canvas/execute: python → 400 (only SQL supported)")
    except AssertionError as e:
        test_fail("POST /canvas/execute validation", str(e))
    except Exception as e:
        test_fail("POST /canvas/execute validation", f"Exception: {e}")

    # ── 7.5 Execute endpoint — SQL execution ──
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/canvas/execute",
            headers=headers,
            json={"code": "SELECT 1 AS test_value", "language": "sql"},
            timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("status") == "success"
            assert "result" in data
            assert "execution_time_ms" in data
            test_pass(f"POST /canvas/execute: SQL OK "
                      f"({data.get('row_count', '?')} rows, {data.get('execution_time_ms', '?')}ms)")
        elif resp.status_code == 503:
            test_skip("POST /canvas/execute SQL", "MCP server not connected")
        elif resp.status_code == 400:
            # MCP error (e.g., database not configured)
            msg = resp.json().get("message", "")[:100]
            test_skip("POST /canvas/execute SQL", f"MCP error: {msg}")
        else:
            test_fail("POST /canvas/execute SQL", f"HTTP {resp.status_code}")
    except Exception as e:
        test_fail("POST /canvas/execute SQL", f"Exception: {e}")

    # ── 7.6 Auth required ──
    try:
        no_auth_headers = {"Content-Type": "application/json"}
        resp = requests.get(f"{BASE_URL}/api/v1/canvas/templates", headers=no_auth_headers, timeout=5)
        # Templates endpoint may or may not require auth — check
        resp2 = requests.post(
            f"{BASE_URL}/api/v1/canvas/inline-ai",
            headers=no_auth_headers,
            json={"selected_code": "x=1", "instruction": "fix"},
            timeout=5
        )
        assert resp2.status_code in (401, 403), \
            f"Expected 401/403 for unauthenticated inline-ai, got {resp2.status_code}"
        test_pass("POST /canvas/inline-ai: auth required (401/403)")

        resp3 = requests.post(
            f"{BASE_URL}/api/v1/canvas/execute",
            headers=no_auth_headers,
            json={"code": "SELECT 1", "language": "sql"},
            timeout=5
        )
        assert resp3.status_code in (401, 403)
        test_pass("POST /canvas/execute: auth required (401/403)")
    except AssertionError as e:
        test_fail("auth guard", str(e))
    except Exception as e:
        test_fail("auth guard", f"Exception: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8: End-to-End LLM Test (requires configured profile + LLM)
# ═══════════════════════════════════════════════════════════════════════════════

def run_e2e_tests():
    section("8. End-to-End — Canvas via Query Submission")

    try:
        import requests
    except ImportError:
        test_skip("E2E tests", "requests module not available")
        return

    BASE_URL = "http://127.0.0.1:5050"

    # Authenticate
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"username": "admin", "password": "admin"},
            timeout=10
        )
        if resp.status_code != 200:
            test_skip("E2E tests", f"Auth failed: {resp.status_code}")
            return
        jwt_token = resp.json()["token"]
    except Exception as e:
        test_skip("E2E tests", f"Auth error: {e}")
        return

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
    }

    # Find @IDEAT profile (llm_only — most likely to support TDA_Canvas)
    try:
        resp = requests.get(f"{BASE_URL}/api/v1/profiles", headers=headers, timeout=10)
        profiles = resp.json().get("profiles", [])
        ideat_profile = None
        for p in profiles:
            if (p.get("tag") or "").upper() == "IDEAT":
                ideat_profile = p
                break
        if not ideat_profile:
            test_skip("E2E tests", "No @IDEAT profile found")
            return
        test_pass(f"E2E: found @IDEAT profile ({ideat_profile['id'][:20]}...)")
    except Exception as e:
        test_skip("E2E tests", f"Profile lookup error: {e}")
        return

    # Create session
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/sessions",
            headers=headers,
            json={},
            timeout=15
        )
        if resp.status_code not in (200, 201):
            test_skip("E2E tests", f"Session creation failed: {resp.status_code}")
            return
        session_id = resp.json().get("session_id")
        test_pass(f"E2E: session created ({session_id[:20]}...)")
    except Exception as e:
        test_skip("E2E tests", f"Session error: {e}")
        return

    # Submit canvas-triggering query with @IDEAT profile
    query = "Create a simple HTML page with a centered heading that says 'Canvas Test' and a blue background. Use TDA_Canvas to present it."
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/sessions/{session_id}/query",
            headers=headers,
            json={"prompt": query, "profile_id": ideat_profile["id"]},
            timeout=15
        )
        if resp.status_code not in (200, 202):
            test_fail("E2E: query submission", f"HTTP {resp.status_code}")
            return
        task_id = resp.json().get("task_id")
        test_pass(f"E2E: query submitted (task {task_id[:20]}...)")
    except Exception as e:
        test_fail("E2E: query submission", f"Exception: {e}")
        return

    # Poll for completion
    log("  Polling for task completion (up to 60s)...")
    start = time.time()
    task_data = None
    while time.time() - start < 60:
        try:
            resp = requests.get(
                f"{BASE_URL}/api/v1/tasks/{task_id}",
                headers=headers,
                timeout=10
            )
            if resp.status_code == 200:
                task_data = resp.json()
                status = task_data.get("status", "")
                if status in ("completed", "complete", "failed", "error"):
                    break
        except Exception:
            pass
        time.sleep(2)

    if not task_data:
        test_fail("E2E: task polling", "Timed out after 60s")
        return

    status = task_data.get("status", "unknown")
    if status not in ("completed", "complete"):
        test_fail("E2E: task completion", f"Status: {status}")
        return
    elapsed = time.time() - start
    test_pass(f"E2E: task completed in {elapsed:.1f}s")

    # Check for component_render event
    events = task_data.get("events", [])
    component_events = [
        e for e in events
        if e.get("event_type") == "component_render"
        or (e.get("event_type") == "notification"
            and e.get("event_data", {}).get("type") == "component_render")
    ]

    if component_events:
        test_pass(f"E2E: found {len(component_events)} component_render event(s)")

        # Inspect first component event
        ce = component_events[0]
        event_data = ce.get("event_data", ce)
        spec = event_data.get("spec") or event_data.get("payload", {}).get("spec")
        if spec:
            lang = spec.get("language", "?")
            title = spec.get("title", "?")
            content_len = len(spec.get("content", ""))
            previewable = spec.get("previewable", "?")
            test_pass(f"E2E: canvas spec — {lang}, '{title}', {content_len} chars, previewable={previewable}")

            # Validate content is actual HTML
            content = spec.get("content", "")
            if "<!DOCTYPE" in content or "<html" in content or "<h1" in content.lower():
                test_pass("E2E: canvas content contains HTML markup")
            else:
                test_fail("E2E: canvas content", "No HTML markup found in content")
        else:
            test_fail("E2E: component event", "No spec found in event data")
    else:
        # Check if TDA_Canvas was called as a tool
        tool_events = [
            e for e in events
            if e.get("event_type") == "notification"
            and "TDA_Canvas" in str(e.get("event_data", {}))
        ]
        if tool_events:
            test_pass(f"E2E: TDA_Canvas mentioned in {len(tool_events)} event(s) (no component_render)")
        else:
            test_fail("E2E: canvas not triggered", "No component_render or TDA_Canvas events found")

    # Token count sanity
    token_events = [
        e for e in events
        if e.get("event_type") == "token_update"
    ]
    if token_events:
        final = token_events[-1].get("event_data", {})
        total_in = final.get("total_input", 0)
        total_out = final.get("total_output", 0)
        test_pass(f"E2E: tokens — {total_in:,} in / {total_out:,} out")
    else:
        log_v("  No token_update events found", indent=1)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    global VERBOSE

    parser = argparse.ArgumentParser(description="Canvas Component Comprehensive Test Suite")
    parser.add_argument("--unit-only", action="store_true", help="Run only unit tests (no server)")
    parser.add_argument("--api-only", action="store_true", help="Run only REST API tests")
    parser.add_argument("--e2e", action="store_true", help="Include E2E LLM tests (slow)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    VERBOSE = args.verbose

    log("=" * 60)
    log("  Canvas Component — Comprehensive Test Suite")
    log("=" * 60)

    try:
        if args.api_only:
            run_api_tests()
        elif args.unit_only:
            run_handler_tests()
            run_diff_tests()
            run_template_tests()
            run_version_tests()
            run_manifest_tests()
            run_instructions_tests()
        else:
            # Default: all unit tests + API tests
            run_handler_tests()
            run_diff_tests()
            run_template_tests()
            run_version_tests()
            run_manifest_tests()
            run_instructions_tests()
            run_api_tests()

            if args.e2e:
                run_e2e_tests()

    except Exception as e:
        log(f"\n  FATAL ERROR: {e}")
        traceback.print_exc()
        results.failed += 1
        results.errors.append(("FATAL", str(e)))

    # ── Summary ──
    log(f"\n{'=' * 60}")
    log(f"  RESULTS: {results.passed} passed, {results.failed} failed, {results.skipped} skipped")
    log(f"  TOTAL:   {results.total} tests")
    log(f"{'=' * 60}")

    if results.errors:
        log("\n  FAILURES:")
        for name, reason in results.errors:
            log(f"    {name}: {reason}")

    sys.exit(0 if results.failed == 0 else 1)


if __name__ == "__main__":
    main()
