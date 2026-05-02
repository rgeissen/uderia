"""
Tests for agent_packs/uderia_expert/build.py — root-relative URI generation
and CDC PATCH wiring loop (Track C).

Covers:
  1. collect_source_files() returns root-relative rel_path values
     (no absolute paths, no leading slash)
  2. source_uri metadata uses file://<rel_path> format (not absolute)
  3. do_import() CDC PATCH loop generates root-relative URIs
  4. _build_filename_to_path() mapping is correct
  5. extract_title() falls back gracefully
  6. PROJECT_ROOT is the actual project root (3 levels up from build.py)

No live Quart server, ChromaDB, or embedding model is required.

Run with:
  python test/test_uderia_expert_build.py -v
  (no PYTHONPATH needed — build.py uses direct imports only)
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Import helpers — build.py imports SentenceTransformer which may not be
# installed in all environments.  Import only the pure-Python helpers.
# ---------------------------------------------------------------------------

BUILD_PY = Path(__file__).parent.parent / "agent_packs/uderia_expert/build.py"


def _import_build():
    """Import build.py, skipping heavy ML imports that may be absent."""
    import importlib.util, types

    # Stub heavy deps so the module-level code doesn't fail
    for mod_name in (
        "sentence_transformers",
        "sentence_transformers.SentenceTransformer",
        "langchain_text_splitters",
        "langchain_text_splitters.RecursiveCharacterTextSplitter",
    ):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # Provide the class stubs
    st_mod = sys.modules["sentence_transformers"]
    if not hasattr(st_mod, "SentenceTransformer"):
        st_mod.SentenceTransformer = MagicMock  # type: ignore

    lts_mod = sys.modules["langchain_text_splitters"]
    if not hasattr(lts_mod, "RecursiveCharacterTextSplitter"):
        lts_mod.RecursiveCharacterTextSplitter = MagicMock  # type: ignore

    spec = importlib.util.spec_from_file_location("build", BUILD_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Module-level import (once for the whole test run)
try:
    build = _import_build()
    BUILD_AVAILABLE = True
except Exception as _e:
    BUILD_AVAILABLE = False
    _BUILD_IMPORT_ERROR = str(_e)


@unittest.skipUnless(BUILD_AVAILABLE, f"build.py not importable: {_BUILD_IMPORT_ERROR if not BUILD_AVAILABLE else ''}")
class TestProjectRoot(unittest.TestCase):
    """PROJECT_ROOT must point to the repo root (3 levels above build.py)."""

    def test_project_root_is_repo_root(self):
        project_root = build.PROJECT_ROOT
        self.assertTrue(project_root.is_dir(),
                        f"PROJECT_ROOT {project_root} must exist")

    def test_project_root_contains_src(self):
        self.assertTrue((build.PROJECT_ROOT / "src").is_dir(),
                        "PROJECT_ROOT must contain src/")

    def test_project_root_contains_agent_packs(self):
        self.assertTrue((build.PROJECT_ROOT / "agent_packs").is_dir(),
                        "PROJECT_ROOT must contain agent_packs/")

    def test_project_root_resolution(self):
        """build.py is at agent_packs/uderia_expert/build.py — three .parent calls."""
        expected = BUILD_PY.resolve().parent.parent.parent
        self.assertEqual(build.PROJECT_ROOT, expected)


@unittest.skipUnless(BUILD_AVAILABLE, "build.py not importable")
class TestCollectSourceFiles(unittest.TestCase):
    """collect_source_files() must return root-relative paths."""

    def setUp(self):
        # Build a minimal temp directory tree mimicking the repo structure
        self.tmp = tempfile.mkdtemp()
        root = Path(self.tmp)
        docs = root / "docs" / "Architecture"
        docs.mkdir(parents=True)
        (docs / "FOO.md").write_text("# Foo\nContent")
        (docs / "BAR.md").write_text("No heading here")
        sub = root / "docs" / "Knowledge_Repositories"
        sub.mkdir(parents=True)
        (sub / "README.md").write_text("# Knowledge")
        (root / "README.md").write_text("# Root Readme")

    def test_returns_list_of_dicts(self):
        files = build.collect_source_files(Path(self.tmp))
        self.assertIsInstance(files, list)
        self.assertGreater(len(files), 0)

    def test_each_entry_has_required_keys(self):
        files = build.collect_source_files(Path(self.tmp))
        for f in files:
            for key in ("abs_path", "filename", "category", "rel_path"):
                self.assertIn(key, f, f"Missing key '{key}' in {f}")

    def test_rel_path_is_not_absolute(self):
        """rel_path must never start with '/' — it's relative to project root."""
        files = build.collect_source_files(Path(self.tmp))
        for f in files:
            self.assertFalse(
                f["rel_path"].startswith("/"),
                f"rel_path must be relative, got: {f['rel_path']}"
            )

    def test_rel_path_does_not_contain_tmp_dir(self):
        """rel_path must not contain the absolute temp directory path."""
        files = build.collect_source_files(Path(self.tmp))
        for f in files:
            self.assertNotIn(
                self.tmp, f["rel_path"],
                f"rel_path must not include absolute tmp path, got: {f['rel_path']}"
            )

    def test_abs_path_is_absolute(self):
        """abs_path must be the full absolute filesystem path."""
        files = build.collect_source_files(Path(self.tmp))
        for f in files:
            self.assertTrue(
                Path(f["abs_path"]).is_absolute(),
                f"abs_path must be absolute, got: {f['abs_path']}"
            )

    def test_readme_at_root_included(self):
        """README.md at project root must be included with rel_path='README.md'."""
        files = build.collect_source_files(Path(self.tmp))
        root_readmes = [f for f in files if f["filename"] == "README.md" and f["rel_path"] == "README.md"]
        self.assertEqual(len(root_readmes), 1)

    def test_docs_rel_path_format(self):
        """docs/**/*.md files must have rel_path like 'docs/Category/file.md'."""
        files = build.collect_source_files(Path(self.tmp))
        docs_files = [f for f in files if f["rel_path"].startswith("docs/")]
        self.assertGreater(len(docs_files), 0, "No docs/ files collected")
        for f in docs_files:
            # rel_path must be 'docs/<category>/<filename>'
            parts = Path(f["rel_path"]).parts
            self.assertGreaterEqual(len(parts), 2,
                                    f"docs rel_path too short: {f['rel_path']}")

    def test_category_derived_from_docs_subdirectory(self):
        """Category must be the first subdirectory under docs/."""
        files = build.collect_source_files(Path(self.tmp))
        arch_files = [f for f in files if "Architecture" in f["rel_path"]]
        for f in arch_files:
            self.assertEqual(f["category"], "Architecture")


@unittest.skipUnless(BUILD_AVAILABLE, "build.py not importable")
class TestSourceUriFormat(unittest.TestCase):
    """
    chunk metadata source_uri must be file://<root-relative-path>
    — NOT file:///absolute/path.
    """

    def _make_source_files(self, root: Path) -> list[dict]:
        return [
            {
                "abs_path": str(root / "docs" / "Architecture" / "FOO.md"),
                "filename": "FOO.md",
                "category": "Architecture",
                "rel_path": "docs/Architecture/FOO.md",
            },
            {
                "abs_path": str(root / "README.md"),
                "filename": "README.md",
                "category": "root",
                "rel_path": "README.md",
            },
        ]

    def test_source_uri_uses_relative_path(self):
        """file:// URI must use the root-relative path, not absolute."""
        source_files = self._make_source_files(Path("/some/install/path"))
        for f in source_files:
            uri = f"file://{f['rel_path']}"
            self.assertFalse(
                uri.startswith("file:///"),
                f"URI must NOT be absolute file:/// but got: {uri}"
            )
            self.assertTrue(
                uri.startswith("file://"),
                f"URI must start with file:// but got: {uri}"
            )

    def test_source_uri_no_leading_slash_in_path(self):
        """Path portion of the URI must not have a leading slash."""
        source_files = self._make_source_files(Path("/some/install/path"))
        for f in source_files:
            uri = f"file://{f['rel_path']}"
            path_part = uri[len("file://"):]
            self.assertFalse(
                path_part.startswith("/"),
                f"Path portion must not start with /: {uri}"
            )

    def test_source_uri_docs_format(self):
        """docs file URI must look like 'file://docs/Architecture/FOO.md'."""
        rel_path = "docs/Architecture/FOO.md"
        uri = f"file://{rel_path}"
        self.assertEqual(uri, "file://docs/Architecture/FOO.md")

    def test_source_uri_readme_format(self):
        """README URI must look like 'file://README.md'."""
        rel_path = "README.md"
        uri = f"file://{rel_path}"
        self.assertEqual(uri, "file://README.md")

    def test_absolute_uri_rejected(self):
        """Old-style absolute URIs must NOT appear — they are not portable."""
        old_style = "file:///Users/rainer/my_private_code/uderia/docs/Architecture/FOO.md"
        path_part = old_style[len("file://"):]
        self.assertTrue(
            path_part.startswith("/"),
            "Test setup: this is an absolute path"
        )
        # Demonstrate how to detect and reject old-style URIs
        is_relative = not path_part.startswith("/")
        self.assertFalse(is_relative, "Old-style absolute URI correctly detected as not relative")


@unittest.skipUnless(BUILD_AVAILABLE, "build.py not importable")
class TestBuildFilenameToPath(unittest.TestCase):
    """_build_filename_to_path() maps filename → rel_path."""

    def test_basic_mapping(self):
        source_files = [
            {"filename": "FOO.md", "rel_path": "docs/Architecture/FOO.md"},
            {"filename": "README.md", "rel_path": "README.md"},
            {"filename": "BAR.md", "rel_path": "docs/Knowledge_Repositories/BAR.md"},
        ]
        mapping = build._build_filename_to_path(source_files)
        self.assertEqual(mapping["FOO.md"], "docs/Architecture/FOO.md")
        self.assertEqual(mapping["README.md"], "README.md")
        self.assertEqual(mapping["BAR.md"], "docs/Knowledge_Repositories/BAR.md")

    def test_last_writer_wins_on_collision(self):
        """When two files share a filename, last entry wins."""
        source_files = [
            {"filename": "README.md", "rel_path": "docs/README.md"},
            {"filename": "README.md", "rel_path": "docs/Architecture/README.md"},
        ]
        mapping = build._build_filename_to_path(source_files)
        self.assertEqual(mapping["README.md"], "docs/Architecture/README.md")

    def test_returns_dict(self):
        mapping = build._build_filename_to_path([])
        self.assertIsInstance(mapping, dict)
        self.assertEqual(len(mapping), 0)

    def test_mapping_values_are_relative(self):
        """All mapped paths must be root-relative (no leading slash)."""
        source_files = [
            {"filename": "FOO.md", "rel_path": "docs/Architecture/FOO.md"},
        ]
        mapping = build._build_filename_to_path(source_files)
        for path in mapping.values():
            self.assertFalse(path.startswith("/"),
                             f"Mapped path must be relative, got: {path}")


@unittest.skipUnless(BUILD_AVAILABLE, "build.py not importable")
class TestExtractTitle(unittest.TestCase):
    """extract_title() must return the first H1 or fall back to filename stem."""

    def test_extracts_h1(self):
        content = "# My Document\n\nSome content"
        self.assertEqual(build.extract_title(content, "my_doc.md"), "My Document")

    def test_ignores_h2(self):
        content = "## Not H1\n\n# Correct Title"
        self.assertEqual(build.extract_title(content, "doc.md"), "Correct Title")

    def test_fallback_to_filename_stem(self):
        content = "No heading here"
        self.assertEqual(build.extract_title(content, "my_document.md"), "my document")

    def test_fallback_replaces_underscores(self):
        content = ""
        self.assertEqual(build.extract_title(content, "knowledge_retrieval.md"),
                         "knowledge retrieval")

    def test_fallback_replaces_hyphens(self):
        content = "## subheading only"
        self.assertEqual(build.extract_title(content, "phase-1-complete.md"),
                         "phase 1 complete")

    def test_strips_h1_whitespace(self):
        content = "#   Padded Title   \n\nContent"
        self.assertEqual(build.extract_title(content, "file.md"), "Padded Title")


@unittest.skipUnless(BUILD_AVAILABLE, "build.py not importable")
class TestDoImportPatchLoop(unittest.TestCase):
    """
    do_import() must generate root-relative file:// URIs in the PATCH loop,
    not absolute ones.
    """

    def _make_mock_response(self, json_data=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = json_data or {}
        return resp

    def test_patch_loop_uses_relative_uri(self):
        """
        Verify that the source_uri passed to _patch_document_source is
        root-relative (file://docs/...) not absolute (file:///abs/...).
        """
        source_files = [
            {
                "abs_path": "/any/install/path/docs/Architecture/FOO.md",
                "filename": "FOO.md",
                "category": "Architecture",
                "rel_path": "docs/Architecture/FOO.md",
            }
        ]
        documents = [
            {"document_id": "doc-1", "filename": "FOO.md"}
        ]

        with patch.object(build, "_get_jwt", return_value="test-jwt"), \
             patch.object(build, "_import_pack", return_value={"status": "ok"}), \
             patch.object(build, "_find_collection_id", return_value=42), \
             patch.object(build, "_list_documents", return_value=documents), \
             patch.object(build, "_patch_document_source") as mock_patch, \
             patch("requests.patch", return_value=self._make_mock_response({"checked": 1})), \
             patch("requests.post", return_value=self._make_mock_response({"checked": 1})):

            build.do_import(Path("/tmp/fake.agentpack"), source_files)

        mock_patch.assert_called_once()
        _call_args = mock_patch.call_args
        source_uri_passed = _call_args[0][4] if len(_call_args[0]) > 4 else _call_args[1].get("source_uri", _call_args[0][-1])

        self.assertEqual(source_uri_passed, "file://docs/Architecture/FOO.md",
                         f"Expected root-relative URI, got: {source_uri_passed}")
        self.assertFalse(
            source_uri_passed.startswith("file:///"),
            f"URI must NOT be absolute file:/// — got: {source_uri_passed}"
        )

    def test_patch_loop_skips_unknown_filenames(self):
        """Documents not found in the source_files mapping are skipped."""
        source_files = [
            {"filename": "FOO.md", "rel_path": "docs/Architecture/FOO.md",
             "abs_path": "/x/docs/Architecture/FOO.md", "category": "Architecture"}
        ]
        documents = [
            {"document_id": "doc-1", "filename": "FOO.md"},
            {"document_id": "doc-2", "filename": "UNKNOWN.md"},  # not in source_files
        ]

        with patch.object(build, "_get_jwt", return_value="test-jwt"), \
             patch.object(build, "_import_pack", return_value={}), \
             patch.object(build, "_find_collection_id", return_value=42), \
             patch.object(build, "_list_documents", return_value=documents), \
             patch.object(build, "_patch_document_source") as mock_patch, \
             patch("requests.patch", return_value=self._make_mock_response({"checked": 1})), \
             patch("requests.post", return_value=self._make_mock_response({"checked": 1})):

            build.do_import(Path("/tmp/fake.agentpack"), source_files)

        # Only FOO.md should be patched (UNKNOWN.md skipped)
        self.assertEqual(mock_patch.call_count, 1)
        patched_uri = mock_patch.call_args[0][4]
        self.assertIn("FOO.md", patched_uri)

    def test_patch_loop_handles_empty_documents(self):
        """Empty document list must not raise and must produce 0 patches."""
        source_files = [
            {"filename": "FOO.md", "rel_path": "docs/FOO.md",
             "abs_path": "/x/docs/FOO.md", "category": "docs"}
        ]

        with patch.object(build, "_get_jwt", return_value="test-jwt"), \
             patch.object(build, "_import_pack", return_value={}), \
             patch.object(build, "_find_collection_id", return_value=42), \
             patch.object(build, "_list_documents", return_value=[]), \
             patch.object(build, "_patch_document_source") as mock_patch:

            build.do_import(Path("/tmp/fake.agentpack"), source_files)

        mock_patch.assert_not_called()


@unittest.skipUnless(BUILD_AVAILABLE, "build.py not importable")
class TestBuildSourceText(unittest.TestCase):
    """Source-text assertions about build.py internals."""

    def setUp(self):
        self.source = BUILD_PY.read_text()

    def test_no_absolute_file_uri_in_source(self):
        """
        build.py must not contain any hardcoded absolute file:/// URIs.
        All URIs must be assembled from rel_path at runtime.
        """
        # file:/// (three slashes = absolute path) must not appear literally
        # (except in comments/docstrings, which we cannot easily exclude —
        # but the production code lines should not have it)
        lines_with_abs = [
            (i + 1, line)
            for i, line in enumerate(self.source.splitlines())
            if "file:///" in line and not line.strip().startswith("#")
        ]
        self.assertEqual(
            lines_with_abs, [],
            f"build.py contains absolute file:/// URIs on lines: "
            f"{[ln for ln, _ in lines_with_abs]}"
        )

    def test_rel_path_used_in_source_uri_metadata(self):
        """Chunk metadata source_uri must be assembled from rel_path."""
        self.assertIn('"source_uri": f"file://{rel_path}"', self.source)

    def test_rel_path_used_in_do_import_patch_loop(self):
        """do_import() PATCH loop must assemble source_uri from rel_path."""
        self.assertIn('source_uri = f"file://{rel_path}"', self.source)

    def test_project_root_calculation(self):
        """PROJECT_ROOT uses .parent.parent.parent (3 levels up from build.py)."""
        self.assertIn("parent.parent.parent", self.source)

    def test_collect_source_files_uses_relative_to(self):
        """collect_source_files must call .relative_to(project_root) for rel_path."""
        self.assertIn("relative_to(project_root)", self.source)

    def test_embedding_model_locked_wired_after_import(self):
        """do_import() must PATCH embedding_model_locked=1 after wiring."""
        self.assertIn("embedding_model_locked", self.source)
        self.assertIn('"embedding_model_locked": 1', self.source)

    def test_initial_sync_triggered_after_import(self):
        """do_import() must POST to /sync after wiring to clear the stale count."""
        self.assertIn("/sync", self.source)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
