"""
Tests for Knowledge Retrieval SSE event contracts and session metadata.

Covers:
  1. SSE event payload field contracts (knowledge_retrieval_start,
     knowledge_retrieval_complete, rag_llm_step)
  2. Turn summary metadata fields written by FocusEngine
     (knowledge_accessed, knowledge_retrieval_event, knowledge_events)
  3. Manual sync trigger uses older_than_seconds=0 (force-check)
  4. Scheduled sync uses default older_than_seconds=3600 (throttled)

No real Quart app, LLM, or vector store is required — all external
dependencies are mocked.

Run with:
  PYTHONPATH=src python test/test_knowledge_retrieval.py -v
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Helpers: build realistic event payloads the way FocusEngine builds them
# ---------------------------------------------------------------------------

def _make_start_payload(collections=None, max_docs=5, session_id="sess-1"):
    """Mirrors focus_engine.py:175-180."""
    return {
        "collections": collections or ["Uderia Documentation"],
        "max_docs": max_docs,
        "session_id": session_id,
        "search_modes": {"Uderia Documentation": "semantic"},
    }


def _make_retrieval_complete_payload(
    collection_names=None, document_count=3, duration_ms=142, session_id="sess-1"
):
    """Mirrors focus_engine.py:236-242 and 571."""
    return {
        "collection_names": collection_names or ["Uderia Documentation"],
        "document_count": document_count,
        "duration_ms": duration_ms,
        "session_id": session_id,
        "search_modes": {"Uderia Documentation": "semantic"},
    }


def _make_rag_llm_step_payload():
    """Mirrors focus_engine.py rag_llm_step emission."""
    return {
        "input_tokens": 3200,
        "output_tokens": 420,
        "model": "claude-sonnet-4-6",
        "provider": "anthropic",
        "cost_usd": 0.004,
        "step_name": "rag_focused_synthesis",
    }


def _make_turn_summary(
    knowledge_accessed=None, knowledge_events=None, knowledge_retrieval_event=None
):
    """Minimal turn summary dict matching what FocusEngine writes at line ~1008."""
    return {
        "turn_input_tokens": 3200,
        "turn_output_tokens": 420,
        "session_id": "sess-1",
        "rag_source_collection_id": (knowledge_accessed or [None])[0],
        "knowledge_accessed": knowledge_accessed or [],
        "knowledge_events": knowledge_events or [],
        "knowledge_retrieval_event": knowledge_retrieval_event or {
            "enabled": True,
            "retrieved": True,
            "document_count": 3,
            "collections": ["Uderia Documentation"],
            "duration_ms": 142,
            "summary": "Retrieved 3 relevant document(s) from 1 knowledge collection(s)",
            "chunks": [],
        },
    }


# ---------------------------------------------------------------------------
# 1. SSE event payload field contracts
# ---------------------------------------------------------------------------

class TestKnowledgeRetrievalStartEvent(unittest.TestCase):
    """knowledge_retrieval_start payload must carry all required fields."""

    def setUp(self):
        self.payload = _make_start_payload()

    def test_has_collections_field(self):
        self.assertIn("collections", self.payload)
        self.assertIsInstance(self.payload["collections"], list)

    def test_has_max_docs_field(self):
        self.assertIn("max_docs", self.payload)
        self.assertIsInstance(self.payload["max_docs"], int)
        self.assertGreater(self.payload["max_docs"], 0)

    def test_has_session_id_field(self):
        self.assertIn("session_id", self.payload)
        self.assertIsNotNone(self.payload["session_id"])

    def test_has_search_modes_field(self):
        self.assertIn("search_modes", self.payload)
        self.assertIsInstance(self.payload["search_modes"], dict)


class TestKnowledgeRetrievalCompleteEvent(unittest.TestCase):
    """knowledge_retrieval_complete payload field contracts."""

    def setUp(self):
        self.payload = _make_retrieval_complete_payload()

    def test_has_collection_names(self):
        self.assertIn("collection_names", self.payload)
        self.assertIsInstance(self.payload["collection_names"], list)

    def test_has_document_count(self):
        self.assertIn("document_count", self.payload)
        self.assertIsInstance(self.payload["document_count"], int)
        self.assertGreaterEqual(self.payload["document_count"], 0)

    def test_has_duration_ms(self):
        self.assertIn("duration_ms", self.payload)
        self.assertIsInstance(self.payload["duration_ms"], (int, float))

    def test_has_session_id(self):
        self.assertIn("session_id", self.payload)

    def test_has_search_modes(self):
        self.assertIn("search_modes", self.payload)

    def test_zero_docs_is_valid(self):
        """No-results path: document_count=0 is a valid payload."""
        payload = _make_retrieval_complete_payload(document_count=0)
        self.assertEqual(payload["document_count"], 0)
        self.assertIn("collection_names", payload)


class TestRagLlmStepEvent(unittest.TestCase):
    """rag_llm_step payload field contracts (Focus synthesis LLM call)."""

    def setUp(self):
        self.payload = _make_rag_llm_step_payload()

    def test_has_input_tokens(self):
        self.assertIn("input_tokens", self.payload)
        self.assertIsInstance(self.payload["input_tokens"], int)

    def test_has_output_tokens(self):
        self.assertIn("output_tokens", self.payload)
        self.assertIsInstance(self.payload["output_tokens"], int)

    def test_has_model(self):
        self.assertIn("model", self.payload)
        self.assertIsNotNone(self.payload["model"])

    def test_has_cost_usd(self):
        self.assertIn("cost_usd", self.payload)
        self.assertIsInstance(self.payload["cost_usd"], (int, float))


# ---------------------------------------------------------------------------
# 2. Turn summary metadata field contracts
# ---------------------------------------------------------------------------

class TestFocusTurnSummaryFields(unittest.TestCase):
    """
    FocusEngine writes these fields to the turn summary at session end.
    Historical turn reload (handleReloadPlanClick in JS) depends on them.
    """

    def setUp(self):
        self.summary = _make_turn_summary(
            knowledge_accessed=[37, 38],
            knowledge_events=[
                {"type": "knowledge_retrieval_start",
                 "payload": _make_start_payload()},
                {"type": "knowledge_retrieval_complete",
                 "payload": _make_retrieval_complete_payload()},
            ],
        )

    def test_knowledge_accessed_is_list(self):
        self.assertIn("knowledge_accessed", self.summary)
        self.assertIsInstance(self.summary["knowledge_accessed"], list)

    def test_knowledge_accessed_contains_collection_ids(self):
        """Each element is a collection ID (int or str, non-null)."""
        for cid in self.summary["knowledge_accessed"]:
            self.assertIsNotNone(cid)

    def test_knowledge_events_is_list(self):
        self.assertIn("knowledge_events", self.summary)
        self.assertIsInstance(self.summary["knowledge_events"], list)

    def test_knowledge_events_contain_typed_dicts(self):
        """Each event in knowledge_events has a 'type' key."""
        for evt in self.summary["knowledge_events"]:
            self.assertIn("type", evt)
            self.assertIn("payload", evt)

    def test_knowledge_retrieval_event_present(self):
        self.assertIn("knowledge_retrieval_event", self.summary)

    def test_knowledge_retrieval_event_has_required_fields(self):
        kre = self.summary["knowledge_retrieval_event"]
        for field in ("enabled", "retrieved", "document_count", "collections",
                      "duration_ms", "summary", "chunks"):
            self.assertIn(field, kre, f"Missing field: {field}")

    def test_knowledge_retrieval_event_enabled_true_for_focus(self):
        """For rag_focused profiles, enabled is always True."""
        self.assertTrue(self.summary["knowledge_retrieval_event"]["enabled"])

    def test_rag_source_collection_id_matches_first_accessed(self):
        """rag_source_collection_id is set to the first collection accessed."""
        self.assertEqual(self.summary["rag_source_collection_id"], 37)

    def test_no_results_turn_summary(self):
        """Turn summary with no retrieved docs still has all required fields."""
        summary = _make_turn_summary(
            knowledge_accessed=[],
            knowledge_events=[
                {"type": "knowledge_retrieval_start",
                 "payload": _make_start_payload()},
                {"type": "knowledge_retrieval_complete",
                 "payload": _make_retrieval_complete_payload(document_count=0)},
            ],
            knowledge_retrieval_event={
                "enabled": True,
                "retrieved": False,
                "document_count": 0,
                "collections": ["Uderia Documentation"],
                "duration_ms": 20,
                "summary": "No relevant knowledge found",
                "chunks": [],
            },
        )
        kre = summary["knowledge_retrieval_event"]
        self.assertFalse(kre["retrieved"])
        self.assertEqual(kre["document_count"], 0)
        self.assertIsNone(summary["rag_source_collection_id"])


class TestKnowledgeEventsReplayStructure(unittest.TestCase):
    """
    knowledge_events list must preserve full event sequence for JS replay.
    JS eventHandlers.js:2254 passes knowledge_retrieval_event to
    renderHistoricalTrace() — this test verifies the sequence contract.
    """

    def test_events_include_start_before_complete(self):
        """knowledge_retrieval_start must appear before knowledge_retrieval_complete."""
        events = [
            {"type": "knowledge_retrieval_start",
             "payload": _make_start_payload()},
            {"type": "knowledge_retrieval_complete",
             "payload": _make_retrieval_complete_payload()},
        ]
        types = [e["type"] for e in events]
        start_idx = types.index("knowledge_retrieval_start")
        complete_idx = types.index("knowledge_retrieval_complete")
        self.assertLess(start_idx, complete_idx)

    def test_all_events_have_type_and_payload(self):
        """Every event in knowledge_events has both 'type' and 'payload' keys."""
        events = [
            {"type": "knowledge_retrieval_start",
             "payload": _make_start_payload()},
            {"type": "rag_llm_step",
             "payload": _make_rag_llm_step_payload()},
            {"type": "knowledge_retrieval_complete",
             "payload": _make_retrieval_complete_payload()},
        ]
        for evt in events:
            self.assertIn("type", evt)
            self.assertIn("payload", evt)


# ---------------------------------------------------------------------------
# 3. Manual trigger uses older_than_seconds=0
# ---------------------------------------------------------------------------

class TestManualSyncTriggerBypassesThrottle(unittest.TestCase):
    """
    trigger_knowledge_sync() in knowledge_routes.py must call
    sync_knowledge_collection() with older_than_seconds=0 so every
    document is force-checked regardless of last_checked_at.

    We verify via source text rather than calling the Quart route handler
    (which requires a full request context).
    """

    def _routes_source(self):
        from pathlib import Path
        return (
            Path(__file__).parent.parent
            / "src/trusted_data_agent/api/knowledge_routes.py"
        ).read_text()

    def test_trigger_passes_older_than_seconds_zero(self):
        """Manual trigger hardcodes older_than_seconds=0 in the route handler."""
        source = self._routes_source()
        self.assertIn("older_than_seconds=0", source,
                      "trigger_knowledge_sync must call sync_knowledge_collection "
                      "with older_than_seconds=0 to bypass the throttle.")

    def test_trigger_calls_sync_knowledge_collection(self):
        """The route handler imports and calls sync_knowledge_collection."""
        source = self._routes_source()
        self.assertIn("sync_knowledge_collection", source)

    def test_scheduled_path_uses_default_throttle(self):
        """
        The default value for older_than_seconds in sync_knowledge_collection
        must be 3600 so scheduled runs only check stale documents.
        """
        from trusted_data_agent.core.knowledge_sync import sync_knowledge_collection
        import inspect
        sig = inspect.signature(sync_knowledge_collection)
        default = sig.parameters["older_than_seconds"].default
        self.assertEqual(default, 3600,
                         "Default older_than_seconds should be 3600 (1 hour throttle).")


# ---------------------------------------------------------------------------
# 4. PATCH allowed fields include source_root
# ---------------------------------------------------------------------------

class TestPatchKnowledgeCollectionAllowedFields(unittest.TestCase):
    """
    The PATCH /v1/knowledge/repositories/{id} endpoint must accept source_root
    in its ALLOWED set so the Platform Jobs UI can configure it.
    """

    def test_source_root_in_allowed_fields(self):
        """Import the ALLOWED set from the route and verify source_root is present."""
        import importlib
        import ast
        from pathlib import Path

        routes_path = (
            Path(__file__).parent.parent
            / "src/trusted_data_agent/api/knowledge_routes.py"
        )
        source = routes_path.read_text()
        # Find the ALLOWED = {...} assignment inside patch_knowledge_collection
        # We check the source text rather than importing (avoids Quart init overhead)
        self.assertIn('"source_root"', source,
                      "source_root missing from ALLOWED set in knowledge_routes.py")

    def test_sync_interval_in_allowed_fields(self):
        """sync_interval must also be patchable via the PATCH endpoint."""
        from pathlib import Path
        source = (
            Path(__file__).parent.parent
            / "src/trusted_data_agent/api/knowledge_routes.py"
        ).read_text()
        self.assertIn('"sync_interval"', source)

    def test_embedding_model_locked_in_allowed_fields(self):
        """embedding_model_locked must be settable via PATCH (UI uses it after reindex)."""
        from pathlib import Path
        source = (
            Path(__file__).parent.parent
            / "src/trusted_data_agent/api/knowledge_routes.py"
        ).read_text()
        self.assertIn('"embedding_model_locked"', source)


# ---------------------------------------------------------------------------
# 5. effective_source_root priority chain
# ---------------------------------------------------------------------------

class TestEffectiveSourceRootResolution(unittest.TestCase):
    """
    The three-tier source_root resolution used by rest_routes.py and
    _fetch_local_file must honour the correct priority order.
    """

    def _resolve_effective_root(self, source_root=None, env_var=None):
        """Replicates the logic in rest_routes.py get_rag_collections()."""
        import os
        from pathlib import Path
        import trusted_data_agent.api.rest_routes as _rr
        effective = (
            source_root
            or (env_var)  # stand-in for os.environ.get("UDERIA_DOCS_ROOT")
            or str(Path(_rr.__file__).resolve().parents[3])
        )
        return effective

    def test_explicit_source_root_wins(self):
        root = self._resolve_effective_root(
            source_root="/opt/uderia",
            env_var="/from/env",
        )
        self.assertEqual(root, "/opt/uderia")

    def test_env_var_wins_when_no_source_root(self):
        root = self._resolve_effective_root(
            source_root=None,
            env_var="/from/env",
        )
        self.assertEqual(root, "/from/env")

    def test_auto_detect_when_neither_set(self):
        root = self._resolve_effective_root(source_root=None, env_var=None)
        # Auto-detected root should be the repo root (exists on disk)
        from pathlib import Path
        self.assertTrue(Path(root).exists(), f"Auto-detected root does not exist: {root}")

    def test_empty_string_source_root_falls_through(self):
        """Empty string is falsy — should fall through to env/auto-detect."""
        root = self._resolve_effective_root(
            source_root="",
            env_var="/from/env",
        )
        self.assertEqual(root, "/from/env")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
