"""
Teradata Enterprise Vector Store backend.

Uses the ``teradatagenai`` Python SDK (``Collection`` V2 API) for ANN search and
``teradataml`` for staging-table SQL operations that enable document-level ID
control required by the abstraction interface.

Registration at import time::

    from trusted_data_agent.vectorstore import teradata_backend  # triggers _register()

Connection config (stored as JSON in collections.backend_config)::

    {
        "host":             "teradata-host.company.com",
        "base_url":         "https://td-endpoint.company.com",
        "username":         "td_user",           # Option A: user/pass auth
        "password":         "td_pass",
        "pat_token":        "eyJ...",            # Option B: PAT token auth
        "pem_file":         "/path/to/cert.pem", # Optional, with PAT token
        "pem_content":      "-----BEGIN...",     # Alternative: inline PEM content
        "database":         "VECTORS_DB",
        "embedding_model":  "amazon.titan-embed-text-v1",
        "search_algorithm": "VECTORDISTANCE",
        "top_k":            10
    }

Staging table design
--------------------
Each collection has a companion Teradata table that provides document-level ID
control (required capabilities GET_BY_ID, DELETE_DOCUMENTS, COUNT)::

    UDERIA_VS_<COLLECTION_NAME_UPPER> (
        CHUNK_ID      VARCHAR(512) NOT NULL,
        CONTENT       CLOB         NOT NULL,
        METADATA_JSON CLOB
    ) UNIQUE PRIMARY INDEX (CHUNK_ID)

The ``VectorStore`` handles embeddings and ANN search server-side (via Bedrock
or Azure OpenAI).  The staging table is managed via ``teradataml.execute_sql``
and ``teradataml.copy_to_sql``.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from .base import VectorStoreBackend
from .capabilities import VectorStoreCapability
from .embedding_providers import EmbeddingProvider
from .filters import MetadataFilter, to_teradata_sql_where
from .types import (
    CollectionConfig,
    CollectionInfo,
    DistanceMetric,
    GetResult,
    IngestionProgress,
    IngestionProgressCallback,
    QueryResult,
    SearchMode,
    ServerSideChunkingConfig,
    VectorDocument,
)

logger = logging.getLogger("vectorstore.teradata")

# ── EVS phase → progress mapping ────────────────────────────────────────────
# Teradata EVS reports status strings like "CREATING (EMBEDDING)".
# Map these to approximate progress percentages and human-readable labels.

_STATUS_PROGRESS: Dict[str, int] = {
    "CREATING": 15,
    "CREATING (PREPARING INPUT)": 20,
    "CREATING (CHUNKING)": 35,
    "CREATING (PROCESSING DOCUMENTS)": 40,
    "CREATING (EMBEDDING)": 55,
    "CREATING (INDEXING)": 80,
    "READY": 100,
    "COMPLETED": 100,
    "SUCCESS": 100,
    # Collection V2 terminal states
    "CREATED": 100,
    "UPDATED": 100,
}

# Matches embedded percentages like "CREATING (PROCESSING DOCUMENTS 42.5 %)"
_EMBEDDED_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# Phase ordering for interpolation when an embedded percentage is present.
# Maps a phase keyword to (phase_start_pct, phase_end_pct) in the overall
# progress bar.  The embedded % is scaled into this range.
_PHASE_RANGES: Dict[str, tuple] = {
    "PROCESSING DOCUMENTS": (25, 50),
    "EMBEDDING": (50, 80),
    "INDEXING": (80, 95),
}


def _resolve_progress_pct(status_str: str, elapsed: int, timeout: int) -> int:
    """Map EVS status to percentage, with time-based fallback for unknown phases.

    Handles three patterns:
    1. Exact match in ``_STATUS_PROGRESS`` (e.g. ``CREATING (EMBEDDING)``).
    2. Embedded percentage like ``CREATING (PROCESSING DOCUMENTS 42.5 %)``.
       The embedded value is scaled into that phase's progress range.
    3. Partial key match (e.g. ``CREATING (EMBEDDING BATCH 2)`` → ``EMBEDDING``).
    4. Time-based fallback for truly unknown statuses.
    """
    # 1. Exact match
    pct = _STATUS_PROGRESS.get(status_str)
    if pct is not None:
        return pct

    upper = status_str.upper()

    # 2. Extract embedded percentage and scale into phase range
    m = _EMBEDDED_PCT_RE.search(status_str)
    if m:
        embedded = float(m.group(1))  # 0-100
        for phase_key, (lo, hi) in _PHASE_RANGES.items():
            if phase_key in upper:
                return int(lo + (embedded / 100.0) * (hi - lo))

    # 3. Partial key match
    for key, val in _STATUS_PROGRESS.items():
        if key in status_str:
            pct = val
            break
    if pct is not None:
        return pct

    # 4. Time-based fallback
    return min(10 + int((elapsed / max(timeout, 1)) * 80), 90)


def _teradata_phase_label(status: str) -> str:
    """Map EVS status string to user-friendly label."""
    s = status.upper()
    if "PREPARING" in s:
        return "Preparing document for processing"
    if "PROCESSING DOCUMENTS" in s:
        m = _EMBEDDED_PCT_RE.search(status)
        if m:
            return f"Processing documents ({m.group(1)}%)"
        return "Processing documents"
    if "CHUNKING" in s:
        return "Splitting document into chunks"
    if "EMBEDDING" in s:
        return "Generating embeddings (this may take a few minutes)"
    if "INDEXING" in s:
        return "Building search index"
    if "READY" in s or "COMPLETED" in s or "SUCCESS" in s:
        return "Processing complete"
    if "FAILED" in s:
        return "Processing failed"
    if "CREATING" in s:
        return "Creating vector store"
    return f"Processing ({status})"


class TeradataVectorBackend(VectorStoreBackend):
    """Teradata Enterprise Vector Store backend.

    Uses ``teradatagenai.Collection`` (V2 API) for server-side embedding and
    ANN search (with optional native BM25 hybrid search), and ``teradataml``
    for staging-table SQL that enables document-level ID operations (delete by
    ID, get by ID, count).

    Both ``teradatagenai`` and ``teradataml`` are optional dependencies —
    ``initialize()`` raises ``RuntimeError`` with install hints if either is absent.
    """

    def __init__(self, connection_config: Dict[str, Any]):
        self._config = connection_config
        self._host: str = connection_config.get("host", "")
        self._base_url: str = connection_config.get("base_url", "")
        self._username: str = connection_config.get("username", "")
        self._password: str = connection_config.get("password", "")
        self._pat_token: str = connection_config.get("pat_token", "")
        self._pem_file: str = connection_config.get("pem_file", "")
        self._pem_content: str = connection_config.get("pem_content", "")
        self._pem_key_name: str = connection_config.get("pem_key_name", "")
        self._pem_tempfile: Optional[str] = None  # temp file path if pem_content used
        self._database: str = connection_config.get("database", "")
        self._embedding_model: str = connection_config.get(
            "embedding_model", "amazon.titan-embed-text-v1"
        )
        self._search_algorithm: str = connection_config.get(
            "search_algorithm", "VECTORDISTANCE"
        )
        self._top_k: int = int(connection_config.get("top_k", 10))
        # Configurable polling for large document ingestion
        self._poll_interval: float = float(connection_config.get("poll_interval", 5.0))
        self._poll_timeout: int = int(connection_config.get("poll_timeout", 1800))  # 30 minutes default

        # VectorStore cache: collection_name -> VectorStore instance
        self._stores: Dict[str, Any] = {}
        # Known collections (VS creation may be deferred until first add)
        self._collections: Set[str] = set()
        self._initialized: bool = False
        self._init_started: bool = False
        self._init_event: asyncio.Event = asyncio.Event()
        # Guard against concurrent create_context() calls invalidating
        # in-flight VS operations (e.g. UI auto-refresh triggering count()
        # while VectorStore.create() is being polled).
        self._vs_operation_active: bool = False
        # Serialise reconnect attempts: only ONE create_context() at a time.
        # Without this, concurrent requests each detect a stale connection
        # and call create_context() simultaneously, invalidating each other
        # in a thundering-herd cascade.
        self._reconnect_lock = asyncio.Lock()
        # Monotonic timestamp of the last successful reconnect.  Callers that
        # detect a stale connection check this: if another coroutine already
        # reconnected *after* the caller's failed attempt, no second
        # create_context() is needed — just retry the SQL.
        self._last_reconnect_ts: float = 0.0
        # Dedicated single-thread executor: teradataml uses SQLAlchemy's
        # SingletonThreadPool (one connection per thread).  The default
        # asyncio.to_thread() dispatches to random threads in a shared pool,
        # so create_context() on thread A is invisible to execute_sql() on
        # thread B → every call sees "connection lost" → constant reconnections.
        # Pinning ALL teradataml/teradatagenai calls to one thread eliminates this.
        self._td_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="teradataml"
        )

    async def _run_in_td_thread(self, fn, *args, **kwargs):
        """Run *fn* on the dedicated teradataml thread.

        All teradataml calls (create_context, execute_sql, VectorStore ops)
        MUST go through this method to stay on the same thread and share
        the SingletonThreadPool connection.
        """
        loop = asyncio.get_running_loop()
        if kwargs:
            fn = functools.partial(fn, **kwargs)
        return await loop.run_in_executor(self._td_executor, fn, *args)

    # ── Identity & capabilities ───────────────────────────────────────────────

    @property
    def backend_type(self) -> str:
        return "teradata"

    def capabilities(self) -> Set[VectorStoreCapability]:
        return {
            VectorStoreCapability.CREATE_COLLECTION,
            VectorStoreCapability.DELETE_COLLECTION,
            VectorStoreCapability.ADD_DOCUMENTS,
            VectorStoreCapability.DELETE_DOCUMENTS,       # via staging table + delete_datasets
            VectorStoreCapability.SIMILARITY_SEARCH,
            VectorStoreCapability.GET_BY_ID,              # via staging table SQL
            VectorStoreCapability.COUNT,                  # via staging table COUNT(*)
            VectorStoreCapability.UPSERT,                 # via Teradata UPI key-column semantics
            VectorStoreCapability.GET_ALL,                # get() with no ids/where returns all docs
            VectorStoreCapability.SERVER_SIDE_EMBEDDING,
            VectorStoreCapability.SERVER_SIDE_CHUNKING,   # document_files ingestion
            VectorStoreCapability.GET_BY_METADATA_FILTER, # JSON_VALUE pre-filter on staging table
            VectorStoreCapability.HYBRID_SEARCH,           # Python-side RRF (dense + lexical legs)
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self, rest_only: bool = False) -> None:
        """Open connections to the Teradata Vector Store API and direct SQL interface.

        Follows the VantageCloud Getting Started pattern:
          1. ``create_context(host, username, password)``  — SQL context (skipped if rest_only=True)
          2. ``set_auth_token(base_url, pat_token, pem_file)`` — VS REST API auth

        Idempotent: returns immediately if already initialized.  Concurrent-safe:
        if another caller is already running ``initialize()``, this method waits
        for it to complete instead of starting a duplicate ``create_context()``.

        Args:
            rest_only: If True, skip SQL connection (create_context). Use for pure
                      server-side chunking where SDK handles all SQL operations internally.
                      Prevents character encoding issues with active SQL connections.
        """
        if self._initialized:
            return

        # Another caller is already initializing — wait for it to finish.
        if self._init_started:
            logger.debug("initialize() waiting for in-progress init to complete")
            await self._init_event.wait()
            return

        self._init_started = True

        try:
            from teradatagenai import set_auth_token  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "The 'teradatagenai' package is required for the Teradata vector backend. "
                "Install it with: pip install teradatagenai"
            ) from exc

        try:
            from teradataml import create_context  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "The 'teradataml' package is required for the Teradata vector backend. "
                "Install it with: pip install teradataml"
            ) from exc

        try:
            if not self._pat_token and not (self._username and self._password):
                raise RuntimeError(
                    "Teradata auth requires either (username + password) or (pat_token + pem_file). "
                    "Provide them in backend_config."
                )

            # 1. SQL context — must be established BEFORE set_auth_token (SDK requirement).
            #    Matches Getting Started cell [4]:
            #      create_context(host=host, username=username, password=my_variable)
            #    SKIP for rest_only mode to avoid character encoding issues with active SQL connections.
            if not rest_only:
                ctx_kwargs: dict = {"host": self._host, "username": self._username}
                if self._password:
                    ctx_kwargs["password"] = self._password
                if self._database:
                    ctx_kwargs["database"] = self._database
                logger.info(f"[TD-SDK] create_context(host={self._host}, database={self._database}, username={self._username})")
                await self._run_in_td_thread(create_context, **ctx_kwargs)
                logger.info("SQL context established via create_context()")
            else:
                logger.info("Skipping SQL context (REST-only mode for server-side chunking)")

            # 2. VS REST API auth — matches Getting Started cell [5]:
            #      ues_uri = env_vars.get("ues_uri")
            #      if ues_uri.endswith("/open-analytics"):
            #          ues_uri = ues_uri[:-15]
            #      set_auth_token(base_url=ues_uri,
            #                     pat_token=env_vars.get("access_token"),
            #                     pem_file=env_vars.get("pem_file"))
            base_url = self._base_url
            if base_url.endswith("/open-analytics"):
                base_url = base_url[:-len("/open-analytics")]

            # If pem_content provided but no pem_file path, write to temp file.
            # CRITICAL: The SDK derives the JWT Key ID (kid) from the PEM *file name*.
            # The temp file MUST be named {key_name}.pem to match the key registered
            # in the VantageCloud Console.
            if self._pem_content and not self._pem_file:
                import tempfile, os
                if not self._pem_key_name:
                    raise RuntimeError(
                        "PEM Key Name is required when providing PEM content. "
                        "Use the key name from VantageCloud Console."
                    )
                tmpdir = None
                pem_path = None
                try:
                    tmpdir = tempfile.mkdtemp(prefix="tda_vs_")
                    pem_path = os.path.join(tmpdir, f"{self._pem_key_name}.pem")
                    with open(pem_path, "w") as f:
                        content = self._pem_content
                        if not content.endswith("\n"):
                            content += "\n"
                        f.write(content)
                    self._pem_tempfile = tmpdir  # track dir for cleanup
                    self._pem_file = pem_path
                except Exception:
                    # Clean up temp dir if PEM write failed
                    if tmpdir and os.path.exists(tmpdir):
                        import shutil
                        shutil.rmtree(tmpdir, ignore_errors=True)
                    raise

            # set_auth_token also hits the REST API — retry on transient
            # CloudFront gateway errors (502/503/504).
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                try:
                    if self._pat_token:
                        pat_kwargs: dict = {
                            "base_url": base_url,
                            "pat_token": self._pat_token,
                        }
                        if self._pem_file:
                            pat_kwargs["pem_file"] = self._pem_file
                        logger.info(f"[TD-SDK] set_auth_token(base_url={base_url}, pat_token=***{self._pat_token[-6:]}, pem_file={self._pem_file})")
                        await self._run_in_td_thread(set_auth_token, **pat_kwargs)
                    else:
                        logger.info(f"[TD-SDK] set_auth_token(base_url={base_url}, username={self._username})")
                        await self._run_in_td_thread(
                            set_auth_token,
                            base_url=base_url,
                            username=self._username,
                            password=self._password,
                        )
                    break  # success
                except Exception as e:
                    err = str(e)
                    is_transient = any(
                        s in err
                        for s in ("502", "503", "504", "Gateway Timeout", "ECONNRESET")
                    )
                    if is_transient and attempt < max_retries:
                        wait = attempt * 3
                        logger.warning(
                            f"set_auth_token attempt {attempt}/{max_retries} "
                            f"failed (transient): {e} — retrying in {wait}s"
                        )
                        await asyncio.sleep(wait)
                    else:
                        raise
            self._initialized = True
            self._init_event.set()  # Wake up any concurrent waiters
            logger.info(
                "TeradataVectorBackend initialized "
                f"(host={self._host}, database={self._database}, "
                f"base_url={base_url}, "
                f"auth={'pat_token' if self._pat_token else 'user/pass'})"
            )
        except RuntimeError:
            self._init_started = False  # Allow retry on failure
            self._init_event.set()  # Wake up waiters so they can see failure
            raise
        except Exception as exc:
            self._init_started = False  # Allow retry on failure
            self._init_event.set()  # Wake up waiters so they can see failure
            raise RuntimeError(
                f"Failed to initialize Teradata backend: {exc}"
            ) from exc

    async def shutdown(self) -> None:
        self._td_executor.shutdown(wait=False)
        # Clean up temp PEM dir if we created one
        if self._pem_tempfile:
            try:
                import shutil
                shutil.rmtree(self._pem_tempfile, ignore_errors=True)
            except Exception:
                pass
            self._pem_tempfile = None
        self._stores.clear()
        self._collections.clear()
        self._initialized = False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _staging_table(self, collection_name: str) -> str:
        """Return a Teradata-safe staging table name for a collection.

        Teradata table names: max 128 chars, alphanumeric + underscore.
        """
        safe = re.sub(r"[^A-Za-z0-9]", "_", collection_name)[:100].upper()
        return f"UDERIA_VS_{safe}"

    def _qualified(self, table_name: str) -> str:
        """Return fully qualified Teradata table name (database.table)."""
        return f"{self._database}.{table_name}"

    async def _reconnect_all(self, *, rest_only: bool = False) -> None:
        """Re-establish both SQL context and VS REST API auth.

        Uses ``_reconnect_lock`` to serialise: if another coroutine already
        reconnected after the caller's failure timestamp, the lock winner's
        fresh connection is reused (no second ``create_context()`` needed).

        Args:
            rest_only: If True, skip SQL ``create_context()`` and only refresh
                      REST API auth.  Used during VS operations (create/add/
                      destroy) where calling ``create_context()`` would
                      overwrite the global teradataml singleton and invalidate
                      the active ``VectorStore`` instance.
        """
        ts_before = time.monotonic()
        async with self._reconnect_lock:
            # Another coroutine may have reconnected while we waited for the lock.
            if self._last_reconnect_ts > ts_before:
                logger.debug("Skipping reconnect — another coroutine already reconnected")
                return

            from teradatagenai import set_auth_token  # type: ignore[import]

            # Guard: skip create_context() while a VS operation is in progress.
            # The VectorStore SDK holds internal state tied to the global
            # teradataml context.  Calling create_context() would overwrite
            # that context, invalidating the VS instance being polled.
            skip_sql = rest_only or self._vs_operation_active
            if skip_sql:
                logger.info(
                    "Reconnect: skipping create_context() — VS operation active "
                    f"(_vs_operation_active={self._vs_operation_active}, rest_only={rest_only}). "
                    "Refreshing REST API auth only."
                )
            else:
                from teradataml import create_context  # type: ignore[import]

                logger.info("teradataml connection lost — re-establishing create_context()")
                ctx_kwargs: dict = {"host": self._host, "username": self._username}
                if self._password:
                    ctx_kwargs["password"] = self._password
                if self._database:
                    ctx_kwargs["database"] = self._database

                try:
                    logger.info(f"[TD-SDK] create_context(host={self._host}, database={self._database}, username={self._username})")
                    await self._run_in_td_thread(create_context, **ctx_kwargs)
                except Exception as ce:
                    ce_str = str(ce)
                    if "TDML_2006" not in ce_str and "Failed to disconnect" not in ce_str:
                        raise
                    # Pool disposal race: remove_context() inside create_context()
                    # failed because another thread was iterating the connection set.
                    # Best-effort cleanup, then retry once.
                    logger.warning(f"create_context() pool disposal race — retrying: {ce}")
                    try:
                        from teradataml import remove_context  # type: ignore[import]
                        await self._run_in_td_thread(remove_context)
                    except Exception:
                        pass  # Pool may still be busy — proceed anyway
                    await asyncio.sleep(1.0)
                    await self._run_in_td_thread(create_context, **ctx_kwargs)

            if self._pat_token:
                base_url = self._base_url
                if base_url.endswith("/open-analytics"):
                    base_url = base_url[:-len("/open-analytics")]
                pat_kwargs: dict = {"base_url": base_url, "pat_token": self._pat_token}
                if self._pem_file:
                    pat_kwargs["pem_file"] = self._pem_file
                logger.info(f"[TD-SDK] set_auth_token(base_url={base_url}, pat_token=***{self._pat_token[-6:]}, pem_file={self._pem_file})")
                await self._run_in_td_thread(set_auth_token, **pat_kwargs)

            self._last_reconnect_ts = time.monotonic()

    @staticmethod
    def _is_connection_lost(exc: BaseException) -> bool:
        """Return True if *exc* indicates a stale / dead Teradata connection.

        Known patterns:
        - ``AttributeError: 'NoneType' object has no attribute 'cursor'``
          (teradataml global context garbage-collected after idle timeout)
        - ``OperationalError: N is not a valid connection pool handle``
          (teradatasql pool invalidated by a concurrent ``create_context()``)
        - ``OperationalError: … socket … / … connection refused|reset …``
          (TCP-level disconnect)
        """
        msg = str(exc).lower()
        if isinstance(exc, AttributeError):
            return "'nonetype'" in msg and "cursor" in msg
        # teradatasql.OperationalError or sqlalchemy OperationalError
        if "operationalerror" in type(exc).__name__.lower() or "operational" in type(exc).__name__.lower():
            return (
                "not a valid connection pool handle" in msg
                or "socket" in msg
                or "connection refused" in msg
                or "connection reset" in msg
                or "broken pipe" in msg
            )
        # Catch-all: any exception mentioning the pool handle pattern
        return "not a valid connection pool handle" in msg

    async def _execute_sql(self, sql: str) -> Any:
        """Run ``teradataml.execute_sql`` with automatic reconnect on stale connection.

        teradataml stores its connection as a module-level global.  After idle
        periods the connection may time out, causing ``execute_sql`` to fail
        with various connection errors (see ``_is_connection_lost``).

        Instead of probing with SELECT 1 (unreliable — connection can die
        between the probe and the real query), this wrapper catches the error
        at the *actual* point of failure, delegates to ``_reconnect_all()``
        (serialised via lock), and retries exactly once.
        """
        from teradataml import execute_sql  # type: ignore[import]

        logger.info(f"[TD-SQL] {sql}")
        try:
            return await self._run_in_td_thread(execute_sql, sql)
        except Exception as exc:
            if not self._is_connection_lost(exc):
                raise
            # If a VS operation (create/add/destroy) is in progress,
            # do NOT call create_context() — it would invalidate the
            # VectorStore instance being polled.
            if self._vs_operation_active:
                logger.warning(
                    "teradataml connection lost but VS operation in progress "
                    "— skipping create_context() to avoid invalidation"
                )
                raise
            await self._reconnect_all()
            return await self._run_in_td_thread(execute_sql, sql)

    @staticmethod
    def _result_to_rows(result: Any) -> List[dict]:
        """Convert execute_sql result to a list of dicts.

        teradataml's execute_sql may return either a teradataml DataFrame
        (has .to_pandas()) or a raw TeradataCursor (has .description +
        .fetchall()).  This helper normalises both to [{"COL": val, ...}].
        """
        if hasattr(result, "to_pandas"):
            pdf = result.to_pandas()
            return [dict(row) for _, row in pdf.iterrows()] if not pdf.empty else []
        # Raw cursor fallback
        if hasattr(result, "description") and hasattr(result, "fetchall"):
            cols = [d[0] for d in result.description]
            return [dict(zip(cols, row)) for row in result.fetchall()]
        return []

    async def _create_collection(self, collection_name: str) -> Any:
        """Create a Collection (V2) instance on the dedicated teradataml thread with retry.

        The SDK constructor checks whether the collection exists and issues a
        warning if not — that warning is expected when we are about to create it.
        Must run on ``_td_executor`` to share the auth context established by
        ``set_auth_token()``.  Retries on transient CloudFront gateway errors.
        """
        import warnings
        from teradatagenai import Collection  # type: ignore[import]

        max_retries = 3
        t = self._VS_STATUS_CALL_TIMEOUT
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"[TD-SDK] Collection('{collection_name}')")
                def _make():
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        return Collection(name=collection_name)
                col = await asyncio.wait_for(
                    self._run_in_td_thread(_make),
                    timeout=t,
                )
                return col
            except asyncio.TimeoutError:
                logger.warning(
                    f"Collection('{collection_name}') attempt {attempt}/{max_retries} "
                    f"timed out after {t}s — thread may be stuck"
                )
                if attempt < max_retries:
                    self._replace_stuck_executor()
                    await self._reconnect_all()
                    await asyncio.sleep(attempt * 3)
                else:
                    raise RuntimeError(
                        f"Collection('{collection_name}') constructor timed out "
                        f"after {max_retries} attempts ({t}s each)"
                    )
            except Exception as e:
                err = str(e)
                is_transient = any(
                    s in err
                    for s in ("502", "503", "504", "Gateway Timeout", "ECONNRESET")
                )
                if is_transient and attempt < max_retries:
                    wait = attempt * 3
                    logger.warning(
                        f"Collection('{collection_name}') attempt {attempt}/{max_retries} "
                        f"failed (transient): {e} — retrying in {wait}s"
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

    async def _get_store(self, collection_name: str) -> Any:
        """Return cached Collection (V2), attaching to an existing collection if not yet cached."""
        if collection_name not in self._stores:
            try:
                col = await self._create_collection(collection_name)
                self._stores[collection_name] = col
                self._collections.add(collection_name)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to attach to existing Teradata Collection '{collection_name}': {exc}"
                ) from exc
        return self._stores[collection_name]

    async def _poll_status(
        self,
        vs: Any,
        operation: str,
        timeout: int = 300,
        interval: int = 5,
        progress_callback: Optional[IngestionProgressCallback] = None,
    ) -> Any:
        """Poll VectorStore until the operation completes, raises on failure or timeout.

        Uses ``vs.get_details()`` as the primary status source because
        ``vs.status()`` is unreliable during creation — it returns ``None``
        or throws ``TDML_2412 Object not found`` during the initial
        ``CREATING (PREPARING INPUT)`` phase, even though the VS is being
        created.  ``vs.get_details()`` consistently returns the correct
        ``vs_status`` column throughout the entire lifecycle.

        Falls back to ``vs.status()`` only when ``get_details()`` is
        unavailable or returns no ``vs_status`` column.

        Returns the (possibly rebuilt) VectorStore instance so callers can
        cache the correct reference.

        When ``progress_callback`` is provided, it is invoked with an
        ``IngestionProgress`` on every status change and periodic heartbeat
        so callers can relay real EVS phase information to the UI.

        Uses a three-phase recovery state machine for resilience:

        1. **Patience** (timeouts 1–2): Don't replace thread — it's waiting
           on a slow REST response.  Linear backoff, emit heartbeats.
        2. **Thread replacement** (timeout 3): Replace stuck thread, call
           ``_reconnect_all(rest_only=True)`` to establish auth context,
           then ``_create_collection()`` with built-in retry.  Saves old ``vs``
           and restores it if recovery fails.
        3. **Backoff** (timeout 4+): Exponential backoff with periodic
           probes.  Stops hammering an overloaded Teradata server.

        Also handles generic poll errors (e.g. stale teradataml context
        from external ``create_context()`` calls) via a 3-error rebuild
        that re-establishes REST auth before creating a fresh VS instance.
        """
        deadline = time.monotonic() + timeout
        start_time = deadline - timeout
        poll_count = 0
        consecutive_errors = 0
        consecutive_timeouts = 0
        in_backoff = False
        last_status = ""
        collection_name = getattr(vs, "name", None) or getattr(vs, "_name", None)
        self._vs_operation_active = True

        while time.monotonic() < deadline:
            try:
                status_str = await self._get_vs_status(vs)
                # Reset all recovery state on any successful poll
                consecutive_errors = 0
                consecutive_timeouts = 0
                in_backoff = False

                # Log status changes and periodic heartbeats
                emit_progress = False
                if status_str != last_status:
                    logger.info(f"VS '{operation}' status: {status_str}")
                    last_status = status_str
                    emit_progress = True
                elif poll_count % 3 == 0:  # Every ~15s at 5s interval
                    elapsed = int(time.monotonic() - (deadline - timeout))
                    logger.info(f"VS '{operation}' still {status_str} ({elapsed}s elapsed)")
                    emit_progress = True

                if emit_progress and progress_callback:
                    elapsed = int(time.monotonic() - (deadline - timeout))
                    progress_callback(IngestionProgress(
                        status=status_str,
                        phase=_teradata_phase_label(status_str),
                        percentage=_resolve_progress_pct(status_str, elapsed, timeout),
                        elapsed_seconds=elapsed,
                    ))

                if any(kw in status_str for kw in (
                    "COMPLETED", "READY", "SUCCESS",
                    # Collection V2 terminal states
                    "CREATED", "UPDATED",
                )):
                    self._vs_operation_active = False
                    return vs
                if any(kw in status_str for kw in ("FAILED", "ERROR", "ABORTED")):
                    self._vs_operation_active = False
                    # Try to capture detailed failure reason.
                    # Prefer col.status() (DataFrame) which contains error_message;
                    # fall back to get_details() (dict) for VectorStore V1 compatibility.
                    fail_detail = ""
                    try:
                        status_df_raw = await self._run_in_td_thread(vs.status)
                        if status_df_raw is not None:
                            pdf = await self._run_in_td_thread(status_df_raw.to_pandas)
                            if not pdf.empty:
                                fail_detail = f" | details: {pdf.to_dict(orient='records')[0]}"
                                if "error_message" in pdf.columns:
                                    err_msg = pdf["error_message"].iloc[0]
                                    if err_msg and str(err_msg).strip():
                                        fail_detail = f" | error: {err_msg}"
                                logger.error(f"VS '{operation}' failure details: {pdf.to_dict(orient='records')[0]}")
                    except Exception:
                        # Fallback: get_details() dict (VectorStore V1)
                        try:
                            details = await self._run_in_td_thread(
                                lambda: vs.get_details(return_type="json")
                            )
                            if details and isinstance(details, dict):
                                fail_detail = f" | details: {details}"
                                logger.error(f"VS '{operation}' failure details: {details}")
                        except Exception:
                            pass
                    raise RuntimeError(
                        f"Teradata VS operation '{operation}' failed with status: {status_str}{fail_detail}"
                    )
            except RuntimeError:
                self._vs_operation_active = False
                raise
            except asyncio.TimeoutError as texc:
                consecutive_errors += 1
                consecutive_timeouts += 1
                elapsed = int(time.monotonic() - start_time)
                logger.warning(
                    f"VS '{operation}' poll timeout #{consecutive_timeouts} "
                    f"(total errors: {consecutive_errors}): {texc}"
                )

                # --- Three-phase recovery state machine ---
                #
                # Phase 1 (patience): Thread is probably just waiting on a slow
                #   REST response from overloaded Teradata.  Don't replace it —
                #   just back off and let the server breathe.
                # Phase 2 (thread replacement): After repeated timeouts the
                #   thread is likely genuinely stuck.  Replace it and establish
                #   auth context on the new thread before creating a fresh VS.
                # Phase 3 (backoff): All recovery failed — exponential backoff
                #   with periodic probes until Teradata recovers.

                if consecutive_timeouts < self._THREAD_REPLACE_THRESHOLD:
                    # Phase 1: Patience — don't replace thread
                    backoff_sleep = min(interval * consecutive_timeouts,
                                        self._MAX_BACKOFF_SLEEP)
                    logger.info(
                        f"VS '{operation}': timeout #{consecutive_timeouts} < "
                        f"threshold {self._THREAD_REPLACE_THRESHOLD} — waiting "
                        f"{backoff_sleep}s (thread NOT replaced, vs preserved)"
                    )
                    # Emit heartbeat so the UI timer keeps ticking
                    if progress_callback:
                        progress_callback(IngestionProgress(
                            status=last_status or "CREATING",
                            phase=_teradata_phase_label(last_status or "CREATING")
                                  + f" ({elapsed}s elapsed, server busy)",
                            percentage=_resolve_progress_pct(
                                last_status or "CREATING", elapsed, timeout),
                            elapsed_seconds=elapsed,
                        ))
                    poll_count += 1
                    await asyncio.sleep(backoff_sleep)
                    continue  # skip the normal sleep at bottom

                elif consecutive_timeouts == self._THREAD_REPLACE_THRESHOLD:
                    # Phase 2: Thread replacement with full context recovery
                    saved_vs = vs
                    logger.info(
                        f"VS '{operation}': {consecutive_timeouts} consecutive "
                        f"timeouts — replacing stuck thread with context recovery"
                    )
                    try:
                        self._replace_stuck_executor()
                        # Establish auth context on new thread BEFORE VectorStore
                        await asyncio.wait_for(
                            self._reconnect_all(rest_only=True),
                            timeout=self._VS_STATUS_CALL_TIMEOUT,
                        )
                        # Use _create_collection() which has built-in 3x retry + 504
                        # detection, instead of raw VectorStore() constructor
                        vs = await self._create_collection(collection_name)
                        logger.info(
                            f"VS '{operation}': thread replaced + context "
                            f"restored, polling resumed"
                        )
                        consecutive_errors = 0
                        consecutive_timeouts = 0
                        in_backoff = False
                    except Exception as reconn_exc:
                        # Recovery failed — Teradata is overloaded.
                        # Restore the old vs and enter backoff mode.
                        vs = saved_vs
                        in_backoff = True
                        logger.warning(
                            f"VS '{operation}': full recovery failed "
                            f"({reconn_exc}). Entering backoff mode with "
                            f"original vs instance."
                        )

                else:
                    # Phase 3: Backoff mode — exponential sleep, periodic probes
                    n = consecutive_timeouts - self._THREAD_REPLACE_THRESHOLD
                    backoff_sleep = min(interval * (2 ** n),
                                        self._MAX_BACKOFF_SLEEP)
                    if n % 3 == 0:
                        logger.info(
                            f"VS '{operation}': backoff probe after "
                            f"{consecutive_timeouts} timeouts ({elapsed}s elapsed)"
                        )
                    else:
                        logger.info(
                            f"VS '{operation}': backoff sleep {backoff_sleep}s "
                            f"(timeout #{consecutive_timeouts}, {elapsed}s elapsed)"
                        )
                    # Emit heartbeat for UI
                    if progress_callback:
                        progress_callback(IngestionProgress(
                            status=last_status or "CREATING",
                            phase=_teradata_phase_label(last_status or "CREATING")
                                  + f" ({elapsed}s elapsed, waiting for server)",
                            percentage=_resolve_progress_pct(
                                last_status or "CREATING", elapsed, timeout),
                            elapsed_seconds=elapsed,
                        ))
                    poll_count += 1
                    await asyncio.sleep(backoff_sleep)
                    continue  # skip the normal sleep at bottom
            except Exception as exc:
                consecutive_errors += 1
                logger.warning(f"VS status poll error during '{operation}': {exc}")

                # After 3 consecutive failures, the teradataml state may be
                # stale (another code path called create_context(), or thread
                # was replaced without context).  Re-establish REST auth and
                # rebuild the VectorStore instance.
                if consecutive_errors >= 3 and collection_name and not in_backoff:
                    saved_vs = vs
                    logger.info(
                        f"VS '{operation}': {consecutive_errors} consecutive "
                        f"poll errors — rebuilding VS with context recovery"
                    )
                    try:
                        await asyncio.wait_for(
                            self._reconnect_all(rest_only=True),
                            timeout=self._VS_STATUS_CALL_TIMEOUT,
                        )
                        vs = await self._create_collection(collection_name)
                        logger.info(
                            f"VS '{operation}': VS instance rebuilt with "
                            f"fresh context, polling resumed"
                        )
                        consecutive_errors = 0
                        consecutive_timeouts = 0
                        in_backoff = False
                    except Exception as reconn_exc:
                        vs = saved_vs  # don't lose the old vs
                        in_backoff = True
                        logger.warning(
                            f"VS '{operation}': rebuild failed ({reconn_exc}), "
                            f"keeping original vs, entering backoff mode"
                        )

            poll_count += 1
            await asyncio.sleep(interval)
        self._vs_operation_active = False
        raise TimeoutError(
            f"Teradata VS operation '{operation}' timed out after {timeout}s "
            f"(last status: {last_status})"
        )

    _VS_STATUS_CALL_TIMEOUT = 60  # seconds – per REST call to Teradata
    _THREAD_REPLACE_THRESHOLD = 3  # consecutive timeouts before replacing thread
    _MAX_BACKOFF_SLEEP = 60        # cap exponential backoff at 60s

    def _replace_stuck_executor(self) -> None:
        """Abandon a stuck dedicated thread and create a fresh executor.

        When ``_run_in_td_thread`` times out, the underlying OS thread is
        still blocked on the network call.  ``ThreadPoolExecutor`` cannot
        interrupt it.  We call ``shutdown(wait=False)`` to stop accepting
        new work, then create a new single-thread pool.  The stuck thread
        will eventually return (or be killed at process exit).

        After replacement, ``_reconnect_all()`` **must** be called to
        re-establish ``create_context`` and ``set_auth_token`` on the new
        thread before any SDK work can proceed.
        """
        logger.warning("Replacing stuck teradataml executor with a fresh thread")
        try:
            self._td_executor.shutdown(wait=False)
        except Exception:
            pass
        self._td_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="teradataml"
        )

    async def _get_vs_status(self, vs: Any) -> str:
        """Extract the canonical status string from a VectorStore instance.

        Prefers ``vs.get_details(return_type='json')`` because
        ``vs.status()`` is unreliable during the creation phase — it
        returns ``None`` or raises ``TDML_2412 Object not found`` while
        the VS is in ``CREATING (PREPARING INPUT)``.

        ``get_details(return_type='json')`` returns a plain dict with a
        ``vs_status`` key that is reliable throughout the full lifecycle.

        Falls back to ``vs.status()`` only when ``get_details()`` is
        unavailable.

        Each REST call is wrapped with ``asyncio.wait_for`` to prevent a
        hanging network call from blocking the poll loop indefinitely.
        Raises ``asyncio.TimeoutError`` when both primary and fallback
        time out, so the caller can trigger thread replacement.
        """
        t = self._VS_STATUS_CALL_TIMEOUT
        timed_out = False

        # Primary: get_details(return_type='json') — plain dict, reliable
        try:
            logger.info("[TD-SDK] vs.get_details(return_type='json')")
            details = await asyncio.wait_for(
                self._run_in_td_thread(
                    lambda: vs.get_details(return_type="json")
                ),
                timeout=t,
            )
            if details and isinstance(details, dict):
                # Collection V2 uses "collection_status"; VectorStore V1 uses "vs_status"
                vs_status = details.get("vs_status") or details.get("collection_status")
                if vs_status is not None:
                    return str(vs_status).upper()
                # Log full response when vs_status is missing to diagnose UNKNOWN
                logger.warning(f"[TD-SDK] get_details() returned dict without status key: keys={list(details.keys())}, values={details}")
            elif details is not None:
                logger.warning(f"[TD-SDK] get_details() returned unexpected type {type(details).__name__}: {details}")
        except asyncio.TimeoutError:
            logger.warning(f"VS get_details() timed out after {t}s")
            timed_out = True
        except Exception as exc:
            if self._is_fatal_vs_error(exc):
                raise RuntimeError(f"VS operation failed (unrecoverable): {exc}") from exc
            pass  # fall through to status()

        # Fallback: status() — works once the VS/Collection is past the initial phase
        try:
            logger.info("[TD-SDK] vs.status()")
            status = await asyncio.wait_for(
                self._run_in_td_thread(vs.status),
                timeout=t,
            )
            if status is not None:
                # status() returns a teradataml DataFrame
                pdf = await asyncio.wait_for(
                    self._run_in_td_thread(status.to_pandas),
                    timeout=t,
                )
                if not pdf.empty:
                    # Collection V2 uses "collection_status"; VectorStore V1 uses "status"
                    status_col = next(
                        (c for c in ("collection_status", "status") if c in pdf.columns),
                        None,
                    )
                    if status_col:
                        return str(pdf[status_col].iloc[0]).upper()
                # Log full DataFrame when status column missing
                logger.warning(f"[TD-SDK] status() DataFrame: empty={pdf.empty}, columns={list(pdf.columns) if not pdf.empty else []}, values={pdf.to_dict() if not pdf.empty else 'empty'}")
                return str(status).upper()
            else:
                logger.warning("[TD-SDK] status() returned None")
        except asyncio.TimeoutError:
            logger.warning(f"VS status() timed out after {t}s")
            timed_out = True
        except Exception as exc:
            logger.warning(f"[TD-SDK] status() exception: {type(exc).__name__}: {exc}")
            if self._is_fatal_vs_error(exc):
                raise RuntimeError(f"VS operation failed (unrecoverable): {exc}") from exc

        if timed_out:
            raise asyncio.TimeoutError("VS status calls timed out — dedicated thread may be stuck")

        return "UNKNOWN"

    # Patterns that indicate an unrecoverable Teradata error — polling should
    # stop immediately instead of looping until the 30-minute outer timeout.
    _FATAL_ERROR_PATTERNS = (
        "No more room in database",
        "No more room in",
        "out of spool space",
        "SPOOL_SPACE",
        "permission denied",
        "Access denied",
        "does not have",         # privilege errors
        "insufficient privileges",
    )

    @classmethod
    def _is_fatal_vs_error(cls, exc: BaseException) -> bool:
        """Return True if the exception represents an unrecoverable VS error.

        Fatal errors (e.g. database full, permission denied) cannot be fixed
        by retrying or replacing the thread — the poll loop should stop
        immediately and report the failure to the user.
        """
        msg = str(exc)
        return any(pattern.lower() in msg.lower() for pattern in cls._FATAL_ERROR_PATTERNS)

    def _build_teradata_ai(self):
        """Build a TeradataAI embedding model instance from the backend config.

        Derives ``api_type`` from the model name unless ``embedding_api_type`` is
        explicitly set in ``backend_config``.  Credentials are resolved in order:

        1. ``authorization`` field  → Teradata authorization object name (preferred)
        2. Explicit credential fields in ``backend_config`` (``aws_access_key`` etc.)

        Returns ``None`` when no credentials are configured and no authorization object
        is set.  Call sites should fall back to passing the model name as a plain string
        (``embeddings_model=self._embedding_model``) in that case — VantageCloud
        servers use server-side IAM and do not require explicit credentials.
        """
        from teradatagenai import TeradataAI  # type: ignore[import]

        model_name = self._embedding_model or ""

        # Derive api_type from model name if not explicitly configured
        api_type = self._config.get("embedding_api_type")
        if not api_type:
            if model_name.startswith("amazon."):
                api_type = "aws"
            elif model_name in ("text-embedding-ada-002", "text-embedding-3-small", "text-embedding-3-large"):
                api_type = "azure"
            else:
                api_type = "aws"  # sensible default for Teradata (Bedrock)

        kwargs: dict = {}
        authorization = self._config.get("authorization")
        if authorization:
            kwargs["authorization"] = authorization
        else:
            if api_type == "aws":
                if self._config.get("aws_access_key"):
                    kwargs["access_key"] = self._config["aws_access_key"]
                if self._config.get("aws_secret_key"):
                    kwargs["secret_key"] = self._config["aws_secret_key"]
                if self._config.get("aws_region"):
                    kwargs["region"] = self._config["aws_region"]
            elif api_type == "azure":
                if self._config.get("azure_api_key"):
                    kwargs["api_key"] = self._config["azure_api_key"]
                if self._config.get("azure_endpoint"):
                    kwargs["api_base"] = self._config["azure_endpoint"]
                if self._config.get("azure_api_version"):
                    kwargs["api_version"] = self._config["azure_api_version"]

        # If no credentials at all and no authorization object, return None.
        # Lake servers use server-side IAM; callers should use embeddings_model=string.
        has_credentials = bool(kwargs)
        if not has_credentials:
            logger.info(
                f"[TD-SDK] No embedding credentials configured — will use "
                f"embeddings_model='{model_name}' (lake server IAM pass-through)"
            )
            return None

        logger.debug(f"[TD-SDK] TeradataAI(api_type={api_type!r}, model_name={model_name!r}, "
                     f"authorization={authorization!r})")
        return TeradataAI(api_type, model_name=model_name, **kwargs)

    def _make_hnsw(self):
        """Create an HNSW indexing algorithm object from the configured search_algorithm.

        Maps V1 search_algorithm strings to Collection V2 HNSW metric values.
        Default metric is COSINE for unknown/V1-specific algorithm names.
        """
        from teradatagenai import HNSW  # type: ignore[import]

        alg = (self._search_algorithm or "").upper()
        if alg in ("COSINE",):
            return HNSW(metric="COSINE")
        if alg in ("EUCLIDEAN",):
            return HNSW(metric="EUCLIDEAN")
        if alg in ("DOT_PRODUCT", "DOTPRODUCT"):
            return HNSW(metric="DOTPRODUCT")
        # Default for V1 values like "VECTORDISTANCE" or any unrecognised value
        return HNSW()

    async def _ensure_staging_table(self, collection_name: str) -> str:
        """Create the staging table if it does not exist. Returns the table name."""
        staging = self._staging_table(collection_name)
        qualified = self._qualified(staging)
        ddl = (
            f"CREATE MULTISET TABLE {qualified} ("
            f"  CHUNK_ID      VARCHAR(512) NOT NULL,"
            f"  CONTENT       CLOB NOT NULL,"
            f"  METADATA_JSON CLOB"
            f") UNIQUE PRIMARY INDEX (CHUNK_ID)"
        )
        try:
            await self._execute_sql(ddl)
        except Exception as exc:
            exc_str = str(exc)
            # Teradata error 3803 = "Table already exists" — tolerate on re-init
            if "3803" in exc_str or "already exists" in exc_str.lower():
                pass
            else:
                raise RuntimeError(
                    f"Failed to create staging table '{qualified}': {exc}"
                ) from exc
        return staging

    async def _staging_count(self, collection_name: str) -> Optional[int]:
        """Return row count from the staging table, or None if the table does not exist."""
        qualified = self._qualified(self._staging_table(collection_name))
        try:
            result = await self._execute_sql(f"SELECT COUNT(*) AS CNT FROM {qualified}")
            rows = self._result_to_rows(result)
            return int(rows[0]["CNT"]) if rows else 0
        except Exception as exc:
            exc_str = str(exc)
            # Teradata error 3807 = "Object does not exist"
            if "3807" in exc_str or "does not exist" in exc_str.lower():
                return None
            logger.warning(f"Unexpected error counting staging table '{qualified}': {exc}")
            return None

    async def _resolve_chunks_table(self, collection_name: str) -> Optional[str]:
        """Discover the SDK's chunks_table name from the index table.

        Server-side chunked collections store chunk text in a
        ``chunks_table_{uuid}`` table.  The name is recorded in the
        ``vectorstore_{collection_name}_index.TableName`` column.
        Returns the fully qualified table name, or None if not found.
        """
        index_table = self._qualified(f"vectorstore_{collection_name}_index")
        try:
            result = await self._execute_sql(
                f"SELECT DISTINCT TRIM(TableName) AS TN FROM {index_table} SAMPLE 1",
            )
            rows = self._result_to_rows(result)
            if rows:
                return self._qualified(rows[0]["TN"])
        except Exception:
            pass
        return None

    async def _vs_table_count(self, collection_name: str) -> Optional[int]:
        """Return row count from the SDK's internal chunks table.

        Server-side chunked collections store data in a ``chunks_table_{uuid}``
        table instead of the staging table.  Returns ``None`` if not found.
        """
        chunks_table = await self._resolve_chunks_table(collection_name)
        if not chunks_table:
            return None
        try:
            result = await self._execute_sql(f"SELECT COUNT(*) AS CNT FROM {chunks_table}")
            rows = self._result_to_rows(result)
            return int(rows[0]["CNT"]) if rows else 0
        except Exception as exc:
            logger.warning(f"Unexpected error counting chunks table '{chunks_table}': {exc}")
            return None

    async def _fetch_metadata(self, collection_name: str, chunk_id: str) -> dict:
        """Retrieve the metadata dict for a single chunk from the staging table."""
        qualified = self._qualified(self._staging_table(collection_name))
        safe_id = chunk_id.replace("'", "''")
        try:
            result = await self._execute_sql(
                f"SELECT METADATA_JSON FROM {qualified} WHERE CHUNK_ID = '{safe_id}'",
            )
            rows = self._result_to_rows(result)
            if rows:
                raw = rows[0].get("METADATA_JSON", rows[0].get("metadata_json", ""))
                return json.loads(raw) if raw else {}
        except Exception:
            pass
        return {}

    async def _fetch_filtered_chunk_ids(
        self, collection_name: str, where: MetadataFilter
    ) -> Optional[set]:
        """Return the set of CHUNK_IDs in the staging table that match *where*.

        Returns ``None`` when the staging table does not exist (server-side
        chunked collection), so the caller can skip the filter gracefully.
        Returns an empty set when the table exists but no rows match.
        """
        # Pass table alias to avoid Teradata Error 3706 where the bare column name
        # METADATA_JSON is parsed as a data type by JSON_VALUE on Teradata 20.x.
        sql_fragment = to_teradata_sql_where(where, json_column="t.METADATA_JSON")
        if not sql_fragment:
            return None

        qualified = self._qualified(self._staging_table(collection_name))
        try:
            result = await self._execute_sql(
                f"SELECT t.CHUNK_ID FROM {qualified} t WHERE {sql_fragment}"
            )
            rows = self._result_to_rows(result)
            return {
                str(r.get("CHUNK_ID", r.get("chunk_id", "")))
                for r in rows
                if r.get("CHUNK_ID", r.get("chunk_id"))
            }
        except Exception as exc:
            exc_str = str(exc)
            if "3807" in exc_str or "does not exist" in exc_str.lower():
                return None  # server-side chunked — no staging table
            logger.warning(
                "Teradata metadata filter query failed — returning unfiltered: %s", exc
            )
            return None

    async def _lexical_search(
        self,
        collection_name: str,
        query_text: str,
        n_results: int,
        allowed_ids: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """Lexical search against staging table CONTENT using tokenised LIKE matching.

        Returns a list of ``{"id": str, "score": float}`` dicts ordered by
        descending lexical score.  Score is the fraction of query tokens found
        in the document (0.0–1.0).

        *allowed_ids* — when provided, restrict results to this set (combines
        metadata pre-filter + lexical search in a single SQL pass).
        """
        # Tokenise: keep words longer than 2 chars, lowercase
        _STOP = {"the", "and", "for", "are", "was", "but", "its", "with",
                 "has", "have", "this", "that", "from", "not", "you", "all"}
        tokens = [
            t.lower() for t in re.findall(r"[A-Za-z0-9]+", query_text)
            if len(t) > 2 and t.lower() not in _STOP
        ]
        if not tokens:
            return []

        qualified = self._qualified(self._staging_table(collection_name))

        # Build LIKE conditions for each token.
        # CONTENT is a CLOB — LOWER() is not supported on CLOB in Teradata.
        # Cast to VARCHAR for case-folding; 64000 is the max VARCHAR length.
        like_parts = " OR ".join(
            f"LOWER(CAST(CONTENT AS VARCHAR(64000))) LIKE '%{t.replace(chr(39), chr(39)*2)}%'"
            for t in tokens
        )

        # Restrict to allowed_ids if provided (for combined metadata + lexical)
        id_filter = ""
        if allowed_ids is not None:
            if not allowed_ids:
                return []  # Metadata filter already excluded everything
            safe_ids = [cid.replace("'", "''") for cid in allowed_ids]
            in_clause = ", ".join(f"'{cid}'" for cid in safe_ids[:500])
            id_filter = f" AND CHUNK_ID IN ({in_clause})"

        sql = (
            f"SELECT CHUNK_ID, CONTENT FROM {qualified}"
            f" WHERE ({like_parts}){id_filter}"
        )

        try:
            result = await self._execute_sql(sql)
            rows = self._result_to_rows(result)
        except Exception as exc:
            exc_str = str(exc)
            if "3807" in exc_str or "does not exist" in exc_str.lower():
                return []  # Server-side collection — no staging table
            logger.warning("Teradata lexical search failed: %s", exc)
            return []

        # Score each row by fraction of tokens present in content
        scored: List[Dict[str, Any]] = []
        for row in rows:
            doc_id = str(row.get("CHUNK_ID", row.get("chunk_id", "")))
            content = (row.get("CONTENT", row.get("content", "")) or "").lower()
            hits = sum(1 for t in tokens if t in content)
            score = hits / len(tokens) if tokens else 0.0
            scored.append({"id": doc_id, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:n_results]

    @staticmethod
    def _rrf_fuse(
        semantic: List[Dict[str, Any]],
        lexical: List[Dict[str, Any]],
        n_results: int,
        k: int = 60,
    ) -> List[str]:
        """Reciprocal Rank Fusion over two ranked lists.

        Each list is ``[{"id": str, "score": float}, ...]`` in descending score
        order.  Returns the top *n_results* CHUNK_IDs ordered by fused score.
        """
        fused: Dict[str, float] = {}
        for rank, item in enumerate(semantic, start=1):
            fused[item["id"]] = fused.get(item["id"], 0.0) + 1.0 / (k + rank)
        for rank, item in enumerate(lexical, start=1):
            fused[item["id"]] = fused.get(item["id"], 0.0) + 1.0 / (k + rank)
        ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        return [doc_id for doc_id, _ in ranked[:n_results]]

    # ── Collection management ─────────────────────────────────────────────────

    async def create_collection(self, config: CollectionConfig) -> CollectionInfo:
        """Create a new collection (staging table). VS creation is deferred to first add()."""
        await self._ensure_staging_table(config.name)
        self._collections.add(config.name)
        logger.info(f"Teradata collection created (staging table ready): '{config.name}'")
        return CollectionInfo(
            name=config.name,
            document_count=0,
            distance_metric=config.distance_metric,
            metadata=config.metadata,
        )

    async def get_or_create_collection(self, config: CollectionConfig) -> CollectionInfo:
        """Attach to an existing collection or create it if absent."""
        await self._ensure_staging_table(config.name)
        self._collections.add(config.name)
        count = await self._staging_count(config.name) or 0
        return CollectionInfo(
            name=config.name,
            document_count=count,
            distance_metric=config.distance_metric,
            metadata=config.metadata,
        )

    async def get_collection_info(self, name: str) -> Optional[CollectionInfo]:
        """Return collection metadata, or None if the staging table does not exist."""
        count = await self._staging_count(name)
        if count is None:
            return None
        return CollectionInfo(name=name, document_count=count)

    async def delete_collection(self, name: str) -> bool:
        """Destroy the VectorStore and drop the companion staging table.

        Returns True only when the VectorStore is confirmed absent from the
        Teradata EVS (via ``VSManager.list()`` verification).  This prevents
        the Uderia database record from being removed while the EVS object
        still exists.
        """
        vs_confirmed_gone = False

        # 1. Destroy the Collection via EVS REST API.
        #    Use cached instance if available, otherwise create a fresh one
        #    so the destroy fires even after server restarts.
        vs = self._stores.pop(name, None)
        if vs is None:
            try:
                vs = await self._create_collection(name)
                logger.info(f"Created transient Collection instance for destroy: '{name}'")
            except Exception as exc:
                logger.warning(f"Could not create Collection instance for '{name}': {exc}")

        if vs is not None:
            try:
                logger.info(f"[TD-SDK] collection.destroy() for '{name}'")
                await self._run_in_td_thread(vs.destroy)
                vs_confirmed_gone = True
                logger.info(f"Teradata Collection '{name}' destroyed")
            except Exception as exc:
                logger.warning(f"Collection destroy failed for '{name}': {exc}")
                # destroy() may have succeeded but the poll timed out or hit a
                # transient error (e.g. CloudFront 504).  Verify whether the
                # collection actually still exists before giving up.
                vs_confirmed_gone = await self._verify_vs_absent(name)

        if not vs_confirmed_gone:
            logger.error(
                f"Teradata VS '{name}' could not be confirmed as destroyed — "
                f"keeping Uderia record to avoid orphaned EVS objects"
            )
            return False

        self._collections.discard(name)

        # 2. Drop staging table
        qualified = self._qualified(self._staging_table(name))
        try:
            await self._execute_sql(f"DROP TABLE {qualified}")
        except Exception as exc:
            exc_str = str(exc)
            if "3807" in exc_str or "does not exist" in exc_str.lower():
                pass  # already gone
            else:
                logger.warning(f"Failed to drop staging table '{qualified}': {exc}")

        return True

    async def _verify_vs_absent(self, name: str) -> bool:
        """Check ``CollectionManager`` to confirm a Collection no longer exists.

        Returns True if the collection is confirmed absent, False if it still
        exists or if the verification itself fails (conservative — assume it exists).
        """
        try:
            from teradatagenai import CollectionManager  # type: ignore[import]

            logger.info(f"[TD-SDK] CollectionManager().list() (verifying '{name}' absent)")
            cm = CollectionManager()
            result = await asyncio.wait_for(
                self._run_in_td_thread(cm.list, return_type="pandas"),
                timeout=self._VS_STATUS_CALL_TIMEOUT,
            )

            if result is None:
                logger.info(f"CollectionManager.list() returned None — assuming '{name}' is gone")
                return True

            # result may be a pandas DataFrame or teradataml DataFrame
            if hasattr(result, "to_pandas"):
                pdf = await asyncio.wait_for(
                    self._run_in_td_thread(result.to_pandas),
                    timeout=self._VS_STATUS_CALL_TIMEOUT,
                )
            else:
                pdf = result

            if pdf.empty:
                logger.info(f"CollectionManager.list() returned empty — '{name}' confirmed absent")
                return True

            # Check if our collection name appears in the listing
            name_upper = name.upper()
            for col in pdf.columns:
                if any(kw in col.lower() for kw in ("name", "collection")):
                    if name_upper in pdf[col].astype(str).str.upper().values:
                        logger.warning(
                            f"Collection '{name}' still present in CollectionManager.list() — "
                            f"destroy did not complete"
                        )
                        return False

            logger.info(f"Collection '{name}' not found in CollectionManager.list() — confirmed absent")
            return True

        except Exception as exc:
            logger.warning(
                f"CollectionManager.list() verification failed for '{name}': {exc} — "
                f"conservatively assuming collection still exists"
            )
            return False

    async def count(self, collection_name: str) -> int:
        """Return the number of documents (staging table or chunks_table)."""
        if self._vs_operation_active:
            return 0  # Don't run SQL while VS create/add is in progress
        staging = await self._staging_count(collection_name)
        if staging:
            return staging
        # Fallback: V1 VectorStore — chunks_table_{uuid} named in index table
        vs_count = await self._vs_table_count(collection_name)
        if vs_count is not None:
            return vs_count
        # Fallback: V2 Collection (FILE_CONTENT_BASED) — no vectorstore_* tables;
        # data lives in the extraction schema table (UDERIA_EXTR_*) we created.
        try:
            _extr = ("UDERIA_EXTR_" + collection_name)[:30].rstrip("_")
            result = await self._execute_sql(
                f"SELECT COUNT(*) AS CNT FROM {self._qualified(_extr)}"
            )
            rows = self._result_to_rows(result)
            if rows:
                return int(rows[0]["CNT"])
        except Exception:
            pass
        return 0

    # ── Document writes ───────────────────────────────────────────────────────

    async def add(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        """Add documents to the collection.

        Steps:
        1. Insert chunk rows into the companion staging table (ID tracking).
        2. Write the same rows to a temporary delta table.
        3a. First add: create VectorStore from the staging table.
        3b. Subsequent adds: call add_datasets() with the delta table.
        4. Drop the temporary delta table.
        """
        if not documents:
            return 0

        import pandas as pd  # type: ignore[import]
        from teradataml import copy_to_sql, execute_sql  # type: ignore[import]

        staging = self._staging_table(collection_name)
        staging_qualified = self._qualified(staging)
        delta_table = f"UDERIA_DELTA_{uuid4().hex[:8].upper()}"
        delta_qualified = self._qualified(delta_table)

        def _safe_text(text: str) -> str:
            """Strip characters that Teradata Error 6706 rejects in SQL strings.

            With charset=UTF-8 on the connection, most Unicode is fine, but
            null bytes and C0/C1 control characters still cause driver failures.
            """
            if not text:
                return text
            # 1. Strip null bytes and C0/C1 control chars that Teradata SQL rejects
            #    even within the Latin-1 range (keep tab \x09, LF \x0a, CR \x0d).
            text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', ' ', text)
            # 2. Encode to Latin-1, replacing characters outside the Latin-1 range
            #    (e.g. U+2019 right-quote from PDF) with '?' so the Teradata LATIN
            #    session charset does not raise Error 6706 (untranslatable character).
            return text.encode("latin-1", errors="replace").decode("latin-1")

        rows = [
            {
                "CHUNK_ID": doc.id,
                "CONTENT": _safe_text(doc.content),
                "METADATA_JSON": _safe_text(json.dumps(doc.metadata or {})),
            }
            for doc in documents
        ]
        df = pd.DataFrame(rows)

        try:
            # Write delta to a named temp table (used for incremental VS ingestion)
            logger.info(f"[TD-SDK] copy_to_sql(table={delta_table}, schema={self._database}, rows={len(df)}, if_exists=replace)")
            await self._run_in_td_thread(
                copy_to_sql,
                df=df,
                table_name=delta_table,
                schema_name=self._database,
                if_exists="replace",
                index=False,
            )

            # Append to staging table — skip CHUNK_IDs already present (UPI guard)
            try:
                existing_ids_result = await self._run_in_td_thread(
                    execute_sql,
                    f"SELECT CHUNK_ID FROM {staging_qualified}",
                )
                existing_ids = {
                    row.get("CHUNK_ID") or row.get("chunk_id")
                    for row in self._result_to_rows(existing_ids_result)
                }
                df_new = df[~df["CHUNK_ID"].isin(existing_ids)]
            except Exception:
                df_new = df  # staging table may not exist yet on first add
            if not df_new.empty:
                logger.info(f"[TD-SDK] copy_to_sql(table={staging}, schema={self._database}, rows={len(df_new)}, if_exists=append)")
                await self._run_in_td_thread(
                    copy_to_sql,
                    df=df_new,
                    table_name=staging,
                    schema_name=self._database,
                    if_exists="append",
                    index=False,
                )
            else:
                logger.info(f"[TD-STAGING] All {len(df)} chunk(s) already in staging — skipping append")

            # Attach to existing collection (or prepare a fresh one).
            # _get_store() caches it in _stores; if the collection doesn't exist
            # on EVS yet, Collection(name=...) won't raise — its .exists will be False.
            from teradatagenai import ContentBasedIndex  # type: ignore[import]
            from teradatagenai.common.constants import CollectionType  # type: ignore[import]

            col = await self._create_collection(collection_name)
            # col.exists was evaluated in the constructor; True means EVS already has it.
            col_on_evs = bool(getattr(col, '_is_exist', None) or
                              collection_name in self._stores)

            if not col_on_evs:
                # First add: collection doesn't exist on EVS yet — create it.
                # IMPORTANT: EVS requires a fully qualified table name in object_names
                # (e.g. "data_scientist.UDERIA_VS_...") so the service can locate
                # the table regardless of its own default database setting.
                # Using an unqualified name causes EVS to fail with CREATE_FAILED.
                index = ContentBasedIndex(
                    object_names=staging_qualified,
                    key_columns=["CHUNK_ID"],
                    data_columns=["CONTENT"],
                )
                indexing_algo = self._make_hnsw()
                # Use embedding_model=TeradataAI(...) so AWS credentials are serialized
                # into the REST payload via to_dict(). Using embeddings_model=string would
                # send only the model name with no credentials → CREATE_FAILED on enterprise
                # servers. On VantageCloud, server-side IAM handles credentials so
                # TeradataAI returns None and we fall back to the string parameter.
                _td_ai = self._build_teradata_ai()
                if _td_ai is not None:
                    _emb_kwargs: dict = {"embedding_model": _td_ai}
                else:
                    _emb_kwargs = {"embeddings_model": self._embedding_model}
                create_kwargs: dict = dict(
                    type=CollectionType.CONTENT_BASED,
                    index=index,
                    indexing_algorithm=indexing_algo,
                    target_database=self._database,
                    ignore_embedding_errors=True,
                    **_emb_kwargs,
                )
                logger.info(
                    f"[TD-SDK] collection.create(type=CONTENT_BASED, "
                    f"object_names={staging_qualified}, key_columns=['CHUNK_ID'], "
                    f"data_columns=['CONTENT'], embedding_model={self._embedding_model})"
                )
                try:
                    await self._run_in_td_thread(
                        col.create,
                        **create_kwargs,
                    )
                except Exception as create_err:
                    if "already exists" in str(create_err):
                        # Race or restart: collection was created before we checked.
                        logger.warning(
                            f"[TD-SDK] col.create() reported already exists — "
                            f"treating as subsequent add and calling col.update() instead"
                        )
                        col_on_evs = True  # fall through to update path below
                    else:
                        raise

            if col_on_evs:
                # Subsequent add (or post-restart recovery): update the Collection with delta.
                delta_index = ContentBasedIndex(
                    object_names=delta_qualified,
                    key_columns=["CHUNK_ID"],
                    data_columns=["CONTENT"],
                )
                logger.info(
                    f"[TD-SDK] collection.update(index.object_names={delta_qualified}, "
                    f"alter_operation=ADD, update_style=MINOR)"
                )
                await self._run_in_td_thread(
                    col.update,
                    index=delta_index,
                    alter_operation="ADD",
                    update_style="MINOR",
                )
                col = await self._poll_status(col, operation="add")
                self._stores[collection_name] = col
                logger.info(
                    f"Added {len(documents)} documents to Teradata Collection '{collection_name}'"
                )
            else:
                col = await self._poll_status(col, operation="create")
                self._stores[collection_name] = col
                self._collections.add(collection_name)
                logger.info(
                    f"Teradata Collection '{collection_name}' created "
                    f"from staging table with {len(documents)} documents"
                )
        finally:
            # Always clean up the delta table
            try:
                await self._execute_sql(f"DROP TABLE {delta_qualified}")
            except Exception:
                pass

        return len(documents)

    async def upsert(
        self,
        collection_name: str,
        documents: List[VectorDocument],
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> int:
        """Insert or update documents. Delegates to add() (key-column semantics in Teradata)."""
        return await self.add(collection_name, documents, embedding_provider)

    async def add_document_files(
        self,
        collection_name: str,
        file_paths: List[str],
        chunking_config: Optional[ServerSideChunkingConfig] = None,
        progress_callback: Optional[IngestionProgressCallback] = None,
    ) -> int:
        """Ingest files via ``Collection.from_documents()`` (V2 Ingestor pipeline).

        The Teradata SDK handles chunking + embedding server-side.

        When ``progress_callback`` is provided it is called once with a
        "CREATING" progress event before blocking; the SDK's internal polling
        handles completion.

        Full initialization is used (create_context + set_auth_token) so that
        subsequent count() and get() calls on the same cached backend instance
        can reach the EVS-managed chunks table via SQL.  Collection.from_documents()
        uses the REST API exclusively and is not affected by the SQL context.
        """
        if not self._initialized:
            await self.initialize()

        config = chunking_config or ServerSideChunkingConfig()

        from teradatagenai import (  # type: ignore[import]
            Collection, LocalConfig, ExtractionSchema,
        )
        from teradatagenai.common.constants import CollectionType  # type: ignore[import]

        # Build BasicIngestor — NVIngestor requires NVIDIA NIM infrastructure which
        # is not available on VantageCloud.  The optimized_chunking flag in
        # Collection V2 means EVS-native chunking; BasicIngestor handles that.
        from teradatagenai import BasicIngestor  # type: ignore[import]
        ingestor_kwargs: dict = {"chunk_size": config.chunk_size}
        if config.header_height and config.header_height > 0:
            ingestor_kwargs["header_height"] = config.header_height
        if config.footer_height and config.footer_height > 0:
            ingestor_kwargs["footer_height"] = config.footer_height
        ingestor = BasicIngestor(**ingestor_kwargs)

        # Detect file type for files_parameters. The lake server fails with
        # 'NoneType has no attribute files_type' when files_parameters is absent.
        _supported = {"pdf", "csv", "json", "jsonl", "parquet", "ndjson", "ldjson"}
        _ext = os.path.splitext(file_paths[0])[1].lstrip(".").lower() if file_paths else ""
        _files_type = _ext if _ext in _supported else "pdf"
        local_config = LocalConfig(files=file_paths, files_type=_files_type)

        if progress_callback:
            progress_callback(IngestionProgress(
                status="CREATING",
                phase="Uploading files and building collection (server-side)",
                percentage=5,
                elapsed_seconds=0,
            ))

        logger.info(
            f"[TD-SDK] Collection.from_documents(name={collection_name}, "
            f"files={file_paths}, embedding_model={self._embedding_model}, "
            f"chunk_size={config.chunk_size}, files_type={_files_type})"
        )

        # from_documents() is a classmethod that runs the full Ingestor pipeline
        # internally (including polling) and returns a Collection instance.
        # On lake servers, TeradataAI returns None and we omit the embedding param
        # so the SDK uses the string model name with server-side IAM.
        _td_ai_docs = self._build_teradata_ai()
        _docs_emb_kwargs: dict = (
            {"embedding": _td_ai_docs} if _td_ai_docs is not None
            else {"embeddings_model": self._embedding_model}
        )

        # Provide an explicit extraction_schema table name to work around a lake-server
        # bug where the server fails with 'NoneType has no attribute table_name' when
        # auto-generating the extraction table name. Use UDERIA_EXTR_ prefix + suffix
        # derived from collection name, truncated to 30 chars total.
        _extr_table = ("UDERIA_EXTR_" + collection_name)[:30].rstrip("_")
        _extraction_schema = ExtractionSchema(table_name=_extr_table)

        result = await self._run_in_td_thread(
            Collection.from_documents,
            name=collection_name,
            documents=local_config,
            type=CollectionType.FILE_CONTENT_BASED,
            ingestor=ingestor,
            extraction_schema=_extraction_schema,
            indexing_algorithm=self._make_hnsw(),
            ignore_embedding_errors=True,
            **_docs_emb_kwargs,
        )

        # from_documents() returns a Collection (or raises on failure)
        col = result if isinstance(result, Collection) else await self._create_collection(collection_name)
        self._stores[collection_name] = col
        self._collections.add(collection_name)

        if progress_callback:
            progress_callback(IngestionProgress(
                status="COMPLETED",
                phase="Processing complete",
                percentage=100,
                elapsed_seconds=0,
            ))

        logger.info(
            f"Teradata Collection '{collection_name}' created from {len(file_paths)} file(s) "
            f"(server-side chunking, optimized={config.optimized_chunking}, "
            f"chunk_size={config.chunk_size})"
        )
        return len(file_paths)

    async def delete(self, collection_name: str, ids: List[str]) -> int:
        """Delete documents by ID.

        1. Fetch their content from the staging table (needed by delete_datasets).
        2. Write those rows to a temporary table.
        3. Call vs.delete_datasets() to remove them from the VectorStore.
        4. Delete the rows from the staging table.
        5. Drop the temporary table.
        """
        if not ids:
            return 0

        import pandas as pd  # type: ignore[import]
        from teradataml import copy_to_sql  # type: ignore[import]

        vs = await self._get_store(collection_name)
        staging_qualified = self._qualified(self._staging_table(collection_name))

        # Build SQL IN clause — chunk IDs are SHA-256 hex strings, safe to embed
        safe_ids = [cid.replace("'", "''") for cid in ids]
        in_clause = ", ".join(f"'{cid}'" for cid in safe_ids)

        # 1. Fetch the documents to be deleted (need CONTENT for VS removal)
        try:
            rows_result = await self._execute_sql(
                f"SELECT CHUNK_ID, CONTENT FROM {staging_qualified} "
                f"WHERE CHUNK_ID IN ({in_clause})",
            )
            rows_df = rows_result.to_pandas()
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch documents for deletion from '{collection_name}': {exc}"
            ) from exc

        if rows_df.empty:
            logger.warning(
                f"delete() called with {len(ids)} IDs but none found in staging table "
                f"for collection '{collection_name}'"
            )
            return 0

        deleted_count = len(rows_df)
        del_table = f"UDERIA_DEL_{uuid4().hex[:8].upper()}"
        del_qualified = self._qualified(del_table)

        try:
            # 2. Load the deleted rows into a temp table for VS removal
            logger.info(f"[TD-SDK] copy_to_sql(table={del_table}, schema={self._database}, rows={len(rows_df)}, if_exists=replace)")
            await self._run_in_td_thread(
                copy_to_sql,
                df=rows_df,
                table_name=del_table,
                schema_name=self._database,
                if_exists="replace",
                index=False,
            )

            # 3. Remove from the Collection via update(alter_operation="DELETE")
            from teradatagenai import ContentBasedIndex  # type: ignore[import]
            del_index = ContentBasedIndex(object_names=del_qualified)
            logger.info(
                f"[TD-SDK] collection.update(index.object_names={del_qualified}, "
                f"alter_operation=DELETE, update_style=MINOR)"
            )
            await self._run_in_td_thread(
                vs.update,
                index=del_index,
                alter_operation="DELETE",
                update_style="MINOR",
            )
            vs = await self._poll_status(vs, operation="delete")

            # 4. Delete from staging table
            await self._execute_sql(
                f"DELETE FROM {staging_qualified} WHERE CHUNK_ID IN ({in_clause})",
            )
        finally:
            # Clean up temp table
            try:
                await self._execute_sql(f"DROP TABLE {del_qualified}")
            except Exception:
                pass

        logger.info(
            f"Deleted {deleted_count} documents from Teradata collection '{collection_name}'"
        )
        return deleted_count

    async def update_metadata(
        self,
        collection_name: str,
        ids: List[str],
        metadatas: List[dict],
    ) -> int:
        """Not supported — Teradata requires re-embedding to modify stored document data."""
        raise NotImplementedError(
            "TeradataVectorBackend does not support metadata-only updates. "
            "Teradata requires re-embedding to update document data. "
            "Use delete() followed by add() with the updated document and metadata."
        )

    # ── Document reads ────────────────────────────────────────────────────────

    async def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 10,
        where: Optional[MetadataFilter] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        include_documents: bool = True,
        include_metadata: bool = True,
        search_mode: SearchMode = SearchMode.SEMANTIC,
        keyword_weight: float = 0.3,
    ) -> QueryResult:
        """Similarity search via the Teradata VectorStore.

        Supports three search modes:
        - SEMANTIC  — dense vector search via EVS SDK (default)
        - HYBRID    — dense + lexical legs fused with Reciprocal Rank Fusion
        - KEYWORD   — lexical-only search against staging table CONTENT

        Metadata filtering (*where*) is applied as a SQL pre-filter against the
        staging table (METADATA_JSON column) before passing candidate IDs to the
        SDK or lexical search. Server-side chunked collections carry no staging
        table and therefore cannot support metadata filtering — a warning is
        logged and results are returned unfiltered.
        """
        search_mode = self._resolve_search_mode(search_mode)

        # ── Step 1: resolve metadata filter → allowed CHUNK_ID set ───────────
        allowed_ids: Optional[set] = None
        if where is not None:
            allowed_ids = await self._fetch_filtered_chunk_ids(collection_name, where)
            if allowed_ids is None:
                # Staging table absent (server-side chunked collection)
                logger.warning(
                    "TeradataVectorBackend: metadata filter ignored for server-side "
                    "chunked collection '%s' (no staging table).",
                    collection_name,
                )
            elif len(allowed_ids) == 0:
                # Filter matched nothing — short-circuit immediately
                return QueryResult(documents=[], distances=[], total_results=0)
            else:
                logger.info(
                    "[TD-FILTER] Metadata pre-filter: %d candidate IDs for '%s'",
                    len(allowed_ids), collection_name,
                )

        # ── Step 2: KEYWORD mode — lexical search only ────────────────────────
        if search_mode == SearchMode.KEYWORD:
            lexical = await self._lexical_search(
                collection_name, query_text, n_results, allowed_ids=allowed_ids
            )
            if lexical:
                return await self._build_query_result(
                    collection_name,
                    [item["id"] for item in lexical],
                    {item["id"]: item["score"] for item in lexical},
                    include_documents=include_documents,
                    include_metadata=include_metadata,
                    score_is_similarity=True,
                )
            # Lexical returned nothing — server-side chunked collection has no staging
            # table for LIKE search.  Fall back to SEMANTIC with a warning.
            logger.warning(
                "[TD-KEYWORD] Lexical search returned no results for '%s' (likely "
                "server-side chunked collection with no staging table). "
                "Falling back to SEMANTIC search.",
                collection_name,
            )
            search_mode = SearchMode.SEMANTIC

        # ── Step 3: SEMANTIC / HYBRID — run dense leg via EVS SDK ────────────
        # Over-fetch to compensate for post-filtering when metadata filter active
        sdk_top_k = n_results if allowed_ids is None else max(n_results * 5, n_results + 100)

        vs = await self._get_store(collection_name)

        # Determine native BM25 availability from backend_config
        bm25_enabled: bool = bool(self._config.get("td_bm25_enabled", False))
        scoring_method: str = self._config.get("td_scoring_method", "rrf")
        sparse_weight: float = float(self._config.get("td_sparse_weight", 0.3))

        # Choose search_type: use native hybrid only when BM25 model is built
        if search_mode == SearchMode.HYBRID and bm25_enabled:
            search_type_str = "hybrid_search"
            logger.info(
                "[TD-BM25] Native hybrid for '%s' (scoring=%s, sparse_weight=%.2f)",
                collection_name, scoring_method, sparse_weight,
            )
        else:
            search_type_str = "semantic_search"

        from teradatagenai import SearchParams  # type: ignore[import]
        sp_kwargs: dict = {"top_k": sdk_top_k, "search_type": search_type_str}
        if search_type_str == "hybrid_search":
            sp_kwargs["scoring_method"] = scoring_method
            sp_kwargs["sparse_weight"] = sparse_weight
        search_params = SearchParams(**sp_kwargs)

        logger.info(
            "[TD-SDK] collection.similarity_search(question='%s...', search_type=%s, top_k=%d)",
            query_text[:60], search_type_str, sdk_top_k,
        )
        try:
            result_obj = await self._run_in_td_thread(
                vs.similarity_search,
                question=query_text,
                search_params=search_params,
                return_type="pandas",
            )
        except Exception as exc:
            if not self._is_connection_lost(exc):
                raise RuntimeError(
                    f"Teradata similarity_search failed for collection '{collection_name}': {exc}"
                ) from exc
            logger.info("teradataml connection lost during query — reconnecting")
            await self._reconnect_all()
            vs = await self._get_store(collection_name)
            result_obj = await self._run_in_td_thread(
                vs.similarity_search,
                question=query_text,
                search_params=search_params,
                return_type="pandas",
            )
        # _SimilaritySearch wrapper vs plain DataFrame
        result_df_raw = (
            result_obj.similar_objects if hasattr(result_obj, "similar_objects")
            else result_obj
        )

        result_df = result_df_raw.rename(columns=str.upper)

        # Detect column names
        score_col = next((c for c in result_df.columns if "SCORE" in c), None)
        content_col = next(
            (c for c in result_df.columns if c in (
                "CONTENT", "TD_FILESPLITS", "FILE_SPLITS", "REV_TEXT", "TEXT", "CHUNKS",
            )),
            None,
        )
        # Prefer CHUNK_ID (our staging-table key) over TD_ID (EVS internal row number).
        # Iterate the preference list and check against available columns — NOT the
        # other way round, which would find TD_ID first because it appears earlier
        # in the DataFrame column order returned by similarity_search.
        id_col = next(
            (c for c in ("CHUNK_ID", "TD_ID") if c in result_df.columns),
            None,
        )

        # Build ranked list from SDK results: [{id, score}]
        is_server_side = "TD_FILENAME" in result_df.columns or "CHUNK_ID" not in result_df.columns
        semantic_ranked: List[Dict[str, Any]] = []
        for _, row in result_df.iterrows():
            doc_id = str(row[id_col]) if id_col else ""
            if not doc_id:
                continue
            # Apply metadata post-filter (skip rows not in allowed set)
            if allowed_ids is not None and doc_id not in allowed_ids:
                continue
            score = float(row[score_col]) if score_col else 0.0
            semantic_ranked.append({"id": doc_id, "score": score})

        # ── Step 4: HYBRID — native BM25 or Python-side RRF ─────────────────
        if search_mode == SearchMode.HYBRID:
            if bm25_enabled:
                # Native BM25: SDK already returned fused results — skip Python RRF
                final_ids = [item["id"] for item in semantic_ranked[:n_results]]
                score_map = {item["id"]: item["score"] for item in semantic_ranked}
                if is_server_side:
                    return self._build_server_side_result(
                        result_df, final_ids, score_col, content_col,
                        include_documents, include_metadata,
                    )
                return await self._build_query_result(
                    collection_name,
                    final_ids,
                    score_map,
                    include_documents=include_documents,
                    include_metadata=include_metadata,
                    score_is_similarity=True,
                )

            # Python-side RRF fallback (BM25 not yet built)
            lexical = await self._lexical_search(
                collection_name, query_text, n_results * 2, allowed_ids=allowed_ids
            )
            if not lexical and is_server_side:
                logger.warning(
                    "[TD-HYBRID] Lexical leg empty for server-side collection '%s' "
                    "(no staging table). Fusion degrades to SEMANTIC only.",
                    collection_name,
                )
            fused_ids = self._rrf_fuse(semantic_ranked, lexical, n_results)
            # Build a score map: use position as a proxy for distance after fusion
            score_map = {doc_id: 1.0 - (i / max(len(fused_ids), 1))
                         for i, doc_id in enumerate(fused_ids)}
            if is_server_side:
                # No staging table — build result directly from SDK DataFrame
                return self._build_server_side_result(
                    result_df, fused_ids, score_col, content_col,
                    include_documents, include_metadata,
                )
            return await self._build_query_result(
                collection_name,
                fused_ids,
                score_map,
                include_documents=include_documents,
                include_metadata=include_metadata,
                score_is_similarity=True,
            )

        # ── Step 5: SEMANTIC — trim and build result ───────────────────────────
        final_ids = [item["id"] for item in semantic_ranked[:n_results]]
        score_map = {item["id"]: item["score"] for item in semantic_ranked}

        # For server-side collections pass the full result_df to avoid extra SQL
        if is_server_side:
            return self._build_server_side_result(
                result_df, final_ids, score_col, content_col,
                include_documents, include_metadata,
            )

        return await self._build_query_result(
            collection_name,
            final_ids,
            score_map,
            include_documents=include_documents,
            include_metadata=include_metadata,
            score_is_similarity=True,
        )

    async def enable_bm25(
        self,
        collection_name: str,
        scoring_method: str = "rrf",
        sparse_weight: float = 0.3,
        progress_callback: Optional[IngestionProgressCallback] = None,
    ) -> None:
        """Enable native Teradata BM25 hybrid search on a Collection.

        Calls ``collection.update(search_params=SearchParams(search_type="hybrid_search"))``
        which triggers the Teradata server to build a BM25 model for the
        collection.  Polls until the build completes (status UPDATED/READY).

        Args:
            collection_name: Name of the collection to enable BM25 for.
            scoring_method:  Fusion method — "rrf" (default), "weighted_sum",
                             "weighted_rrf".
            sparse_weight:   BM25 weight in the range 0.0–1.0 (default 0.3).
            progress_callback: Optional callback receiving IngestionProgress
                             updates while the BM25 model is being built.
        """
        from teradatagenai import SearchParams  # type: ignore[import]

        col = await self._get_store(collection_name)
        sp = SearchParams(
            search_type="hybrid_search",
            scoring_method=scoring_method,
            sparse_weight=sparse_weight,
        )
        logger.info(
            "[TD-BM25] Enabling native BM25 for '%s' (scoring=%s, sparse_weight=%.2f)",
            collection_name, scoring_method, sparse_weight,
        )
        await self._run_in_td_thread(col.update, search_params=sp)
        await self._poll_status(
            col,
            operation="enable_bm25",
            timeout=self._poll_timeout,
            interval=int(self._poll_interval),
            progress_callback=progress_callback,
        )
        logger.info("[TD-BM25] BM25 model built for '%s'", collection_name)

    async def _build_query_result(
        self,
        collection_name: str,
        ordered_ids: List[str],
        score_map: Dict[str, float],
        include_documents: bool,
        include_metadata: bool,
        score_is_similarity: bool = True,
    ) -> QueryResult:
        """Build a QueryResult by fetching content+metadata from the staging table."""
        if not ordered_ids:
            return QueryResult(documents=[], distances=[], total_results=0)

        # Batch-fetch content+metadata for the ordered IDs
        safe_ids = [cid.replace("'", "''") for cid in ordered_ids]
        in_clause = ", ".join(f"'{cid}'" for cid in safe_ids)
        qualified = self._qualified(self._staging_table(collection_name))
        try:
            result = await self._execute_sql(
                f"SELECT CHUNK_ID, CONTENT, METADATA_JSON "
                f"FROM {qualified} WHERE CHUNK_ID IN ({in_clause})"
            )
            rows = self._result_to_rows(result)
        except Exception as exc:
            logger.warning("_build_query_result staging fetch failed: %s", exc)
            rows = []

        row_by_id: Dict[str, dict] = {}
        for row in rows:
            cid = str(row.get("CHUNK_ID", row.get("chunk_id", "")))
            row_by_id[cid] = row

        docs: List[VectorDocument] = []
        distances: List[float] = []
        for doc_id in ordered_ids:
            row = row_by_id.get(doc_id, {})
            content = ""
            if include_documents:
                content = str(row.get("CONTENT", row.get("content", "")))
            meta: dict = {}
            if include_metadata:
                raw = row.get("METADATA_JSON", row.get("metadata_json", ""))
                try:
                    meta = json.loads(raw) if raw else {}
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            score = score_map.get(doc_id, 0.0)
            distance = (1.0 - score) if score_is_similarity else score
            docs.append(VectorDocument(id=doc_id, content=content, metadata=meta))
            distances.append(distance)

        return QueryResult(documents=docs, distances=distances, total_results=len(docs))

    def _build_server_side_result(
        self,
        result_df,
        final_ids: List[str],
        score_col: Optional[str],
        content_col: Optional[str],
        include_documents: bool,
        include_metadata: bool,
    ) -> QueryResult:
        """Build QueryResult for server-side chunked collections from the SDK DataFrame."""
        id_col = next(
            (c for c in ("CHUNK_ID", "TD_ID") if c in result_df.columns), None
        )
        id_set = set(final_ids)
        docs: List[VectorDocument] = []
        distances: List[float] = []
        for _, row in result_df.iterrows():
            doc_id = str(row[id_col]) if id_col else ""
            if doc_id not in id_set:
                continue
            content = str(row[content_col]) if (content_col and include_documents) else ""
            score = float(row[score_col]) if score_col else 0.0
            meta: dict = {}
            if include_metadata:
                if "TD_FILENAME" in result_df.columns:
                    meta["filename"] = str(row.get("TD_FILENAME", ""))
                if "TABLENAME" in result_df.columns:
                    meta["table_name"] = str(row.get("TABLENAME", ""))
            docs.append(VectorDocument(id=doc_id, content=content, metadata=meta))
            distances.append(1.0 - score)
        # Re-order to match final_ids order
        order = {cid: i for i, cid in enumerate(final_ids)}
        paired = sorted(zip(docs, distances), key=lambda x: order.get(x[0].id, 999))
        if paired:
            docs, distances = zip(*paired)  # type: ignore[assignment]
            docs, distances = list(docs), list(distances)
        return QueryResult(documents=docs, distances=distances, total_results=len(docs))

    async def get(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        where: Optional[MetadataFilter] = None,
        include_documents: bool = True,
        include_metadata: bool = True,
        include_embeddings: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> GetResult:
        """Fetch documents from staging table, falling back to vectorstoreV_ table.

        Client-side chunked collections store data in the staging table
        (UDERIA_VS_{name}) with CHUNK_ID / CONTENT / METADATA_JSON columns.

        Server-side chunked collections have no staging table — data lives in
        Teradata's internal vectorstoreV_{name} table with TD_ID / FILE_SPLITS /
        TD_FILENAME columns.  This method transparently falls back to that table.
        """

        # ── Try staging table first (client-side chunking) ─────────────────
        staging_qualified = self._qualified(self._staging_table(collection_name))
        staging_exists = True

        # Translate metadata filter to SQL — use table alias to avoid Teradata
        # Error 3706 where bare METADATA_JSON is mis-parsed as a type name by JSON_VALUE.
        meta_sql_t = to_teradata_sql_where(where, json_column="t.METADATA_JSON") if where is not None else None
        meta_sql_tbl = to_teradata_sql_where(where, json_column="tbl.METADATA_JSON") if where is not None else None

        try:
            if ids is not None:
                safe_ids = [cid.replace("'", "''") for cid in ids]
                in_clause = ", ".join(f"'{cid}'" for cid in safe_ids)
                id_where = f"t.CHUNK_ID IN ({in_clause})"
                combined_where = (
                    f"{id_where} AND ({meta_sql_t})" if meta_sql_t else id_where
                )
                sql = (
                    f"SELECT t.CHUNK_ID, t.CONTENT, t.METADATA_JSON "
                    f"FROM {staging_qualified} t "
                    f"WHERE {combined_where}"
                )
            else:
                meta_and = f"WHERE {meta_sql_tbl}" if meta_sql_tbl else ""
                row_start = offset + 1
                row_end = (offset + limit) if limit else 2_000_000_000
                sql = (
                    f"SELECT CHUNK_ID, CONTENT, METADATA_JSON FROM ("
                    f"  SELECT tbl.CHUNK_ID, tbl.CONTENT, tbl.METADATA_JSON,"
                    f"         ROW_NUMBER() OVER (ORDER BY tbl.CHUNK_ID) AS RN"
                    f"  FROM {staging_qualified} tbl {meta_and}"
                    f") T WHERE RN BETWEEN {row_start} AND {row_end}"
                )

            result = await self._execute_sql(sql)
            rows = self._result_to_rows(result)

        except Exception as exc:
            exc_str = str(exc)
            if "3807" in exc_str or "does not exist" in exc_str.lower():
                staging_exists = False
                rows = []
            else:
                raise RuntimeError(
                    f"Failed to fetch documents from staging table "
                    f"for collection '{collection_name}': {exc}"
                ) from exc

        # Parse staging table rows
        if staging_exists and rows:
            docs: List[VectorDocument] = []
            for row in rows:
                doc_id = str(row.get("CHUNK_ID", row.get("chunk_id", "")))
                content = (
                    str(row.get("CONTENT", row.get("content", "")))
                    if include_documents
                    else ""
                )
                meta: dict = {}
                if include_metadata:
                    raw = row.get("METADATA_JSON", row.get("metadata_json", ""))
                    try:
                        meta = json.loads(raw) if raw else {}
                    except (json.JSONDecodeError, TypeError):
                        meta = {}
                docs.append(VectorDocument(id=doc_id, content=content, metadata=meta))
            return GetResult(documents=docs, total_count=len(docs))

        # ── Fallback: server-side chunked collection ──────────────────────────
        chunks_qualified = await self._resolve_chunks_table(collection_name)

        if not chunks_qualified:
            # V2 Collection (FILE_CONTENT_BASED): no vectorstore_* tables exist.
            # Data lives in the extraction schema table (UDERIA_EXTR_*) we created.
            # Only TD_FILENAME and TD_FILESPLITS columns exist — no TD_ID.
            _extr = ("UDERIA_EXTR_" + collection_name)[:30].rstrip("_")
            extr_qualified = self._qualified(_extr)
            try:
                if ids is not None:
                    # IDs are in format "filename#row_number" (set during browse).
                    # Parse the RN suffix so we can select the exact row via
                    # ROW_NUMBER() rather than matching on TD_FILENAME (which is
                    # the same for every chunk in a single-file collection).
                    rns = []
                    for cid in ids:
                        if "#" in cid:
                            try:
                                rns.append(int(cid.rsplit("#", 1)[1]))
                            except ValueError:
                                pass
                    if rns:
                        rn_list = ", ".join(str(r) for r in rns)
                        sql = (
                            f"SELECT TD_FILENAME, TD_FILESPLITS, RN FROM ("
                            f"  SELECT TD_FILENAME, TD_FILESPLITS,"
                            f"         ROW_NUMBER() OVER (ORDER BY TD_FILENAME) AS RN"
                            f"  FROM {extr_qualified}"
                            f") T WHERE RN IN ({rn_list})"
                        )
                    else:
                        # Fallback: no #rn suffix — match by filename
                        filenames = [cid.replace("'", "''") for cid in ids]
                        in_clause = ", ".join(f"'{fn}'" for fn in filenames)
                        sql = (
                            f"SELECT TD_FILENAME, TD_FILESPLITS, 0 AS RN "
                            f"FROM {extr_qualified} "
                            f"WHERE TD_FILENAME IN ({in_clause})"
                        )
                else:
                    row_start = offset + 1
                    row_end = (offset + limit) if limit else 2_000_000_000
                    sql = (
                        f"SELECT TD_FILENAME, TD_FILESPLITS, RN FROM ("
                        f"  SELECT TD_FILENAME, TD_FILESPLITS,"
                        f"         ROW_NUMBER() OVER (ORDER BY TD_FILENAME) AS RN"
                        f"  FROM {extr_qualified}"
                        f") T WHERE RN BETWEEN {row_start} AND {row_end}"
                    )
                result = await self._execute_sql(sql)
                v2_rows = self._result_to_rows(result)
            except Exception as exc:
                logger.warning(
                    "V2 extraction table query failed for '%s': %s",
                    collection_name, exc,
                )
                return GetResult(documents=[], total_count=0)

            docs = []
            for row in v2_rows:
                fn = str(row.get("TD_FILENAME", row.get("td_filename", "")))
                rn = int(row.get("RN", row.get("rn", 0)))
                content = (
                    str(row.get("TD_FILESPLITS", row.get("td_filesplits", "")))
                    if include_documents else ""
                )
                meta = {
                    "source_filename": fn,
                    "document_id": fn,
                    "chunk_index": rn,
                } if include_metadata else {}
                docs.append(VectorDocument(id=f"{fn}#{rn}", content=content, metadata=meta))
            return GetResult(documents=docs, total_count=len(docs))

        # Use SELECT * because the EVS SDK may name the content column
        # differently depending on version/parameters (file_splits, chunks,
        # content, etc.).  Column detection mirrors the query() approach.
        try:
            if ids is not None:
                safe_ids = [cid.replace("'", "''") for cid in ids]
                in_clause = ", ".join(f"'{cid}'" for cid in safe_ids)
                sql = (
                    f"SELECT * FROM {chunks_qualified} "
                    f"WHERE CAST(TD_ID AS VARCHAR(100)) IN ({in_clause})"
                )
            else:
                row_start = offset + 1
                row_end = (offset + limit) if limit else 2_000_000_000
                sql = (
                    f"SELECT * FROM ("
                    f"  SELECT T2.*, ROW_NUMBER() OVER (ORDER BY TD_ID) AS RN"
                    f"  FROM {chunks_qualified} T2"
                    f") T WHERE RN BETWEEN {row_start} AND {row_end}"
                )

            result = await self._execute_sql(sql)
            vs_rows = self._result_to_rows(result)

        except Exception as exc:
            exc_str = str(exc)
            if "3807" in exc_str or "does not exist" in exc_str.lower():
                return GetResult(documents=[], total_count=0)
            raise RuntimeError(
                f"Failed to fetch documents from chunks table "
                f"'{chunks_qualified}' for collection '{collection_name}': {exc}"
            ) from exc

        # Dynamically detect column names (case-insensitive).
        # The SDK uses varying names: file_splits, chunks, content, etc.
        cols_upper: Dict[str, str] = {}
        if vs_rows:
            cols_upper = {k.upper(): k for k in vs_rows[0].keys()}

        id_key = cols_upper.get("TD_ID", "TD_ID")
        # Content column: try known names in priority order
        content_key = None
        for candidate in ("FILE_SPLITS", "CHUNKS", "CONTENT", "REV_TEXT", "TEXT"):
            if candidate in cols_upper:
                content_key = cols_upper[candidate]
                break
        filename_key = cols_upper.get("TD_FILENAME", "TD_FILENAME")

        docs = []
        for row in vs_rows:
            doc_id = str(row.get(id_key, ""))
            content = ""
            if include_documents and content_key:
                content = str(row.get(content_key, ""))
            meta: dict = {}
            if include_metadata:
                filename = row.get(filename_key, "")
                if filename:
                    meta["filename"] = str(filename)
            docs.append(VectorDocument(id=doc_id, content=content, metadata=meta))

        return GetResult(documents=docs, total_count=len(docs))


# ── Auto-register this backend when module is imported ────────────────────────

def _register() -> None:
    from .factory import register_backend
    register_backend("teradata", TeradataVectorBackend)


_register()
