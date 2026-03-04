"""
Teradata Enterprise Vector Store backend.

Uses the real ``teradatagenai`` Python SDK (``VectorStore``) for ANN search and
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
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from .base import VectorStoreBackend
from .capabilities import VectorStoreCapability
from .embedding_providers import EmbeddingProvider
from .filters import MetadataFilter
from .types import (
    CollectionConfig,
    CollectionInfo,
    DistanceMetric,
    GetResult,
    QueryResult,
    ServerSideChunkingConfig,
    VectorDocument,
)

logger = logging.getLogger("vectorstore.teradata")

class TeradataVectorBackend(VectorStoreBackend):
    """Teradata Enterprise Vector Store backend.

    Uses ``teradatagenai.VectorStore`` for server-side embedding and ANN search,
    and ``teradataml`` for staging-table SQL that enables document-level ID
    operations (delete by ID, get by ID, count).

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

        # VectorStore cache: collection_name -> VectorStore instance
        self._stores: Dict[str, Any] = {}
        # Known collections (VS creation may be deferred until first add)
        self._collections: Set[str] = set()
        self._initialized: bool = False
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

    # ── Identity & capabilities ───────────────────────────────────────────────

    @property
    def backend_type(self) -> str:
        return "teradata"

    def capabilities(self) -> Set[VectorStoreCapability]:
        return {
            VectorStoreCapability.CREATE_COLLECTION,
            VectorStoreCapability.DELETE_COLLECTION,
            VectorStoreCapability.ADD_DOCUMENTS,
            VectorStoreCapability.DELETE_DOCUMENTS,      # via staging table + delete_datasets
            VectorStoreCapability.SIMILARITY_SEARCH,
            VectorStoreCapability.GET_BY_ID,             # via staging table SQL
            VectorStoreCapability.COUNT,                 # via staging table COUNT(*)
            VectorStoreCapability.UPSERT,                # via Teradata UPI key-column semantics
            VectorStoreCapability.GET_ALL,               # get() with no ids/where returns all docs
            VectorStoreCapability.SERVER_SIDE_EMBEDDING,
            VectorStoreCapability.SERVER_SIDE_CHUNKING,  # document_files ingestion
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Open connections to the Teradata Vector Store API and direct SQL interface.

        Follows the VantageCloud Lake Getting Started pattern:
          1. ``create_context(host, username, password)``  — SQL context
          2. ``set_auth_token(base_url, pat_token, pem_file)`` — VS REST API auth
        """
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
            ctx_kwargs: dict = {"host": self._host, "username": self._username}
            if self._password:
                ctx_kwargs["password"] = self._password
            if self._database:
                ctx_kwargs["database"] = self._database
            await asyncio.to_thread(create_context, **ctx_kwargs)

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
            # in the VantageCloud Lake Console.
            if self._pem_content and not self._pem_file:
                import tempfile, os
                if not self._pem_key_name:
                    raise RuntimeError(
                        "PEM Key Name is required when providing PEM content. "
                        "Use the key name from VantageCloud Lake Console."
                    )
                tmpdir = tempfile.mkdtemp(prefix="tda_vs_")
                pem_path = os.path.join(tmpdir, f"{self._pem_key_name}.pem")
                with open(pem_path, "w") as f:
                    content = self._pem_content
                    if not content.endswith("\n"):
                        content += "\n"
                    f.write(content)
                self._pem_tempfile = tmpdir  # track dir for cleanup
                self._pem_file = pem_path

            if self._pat_token:
                pat_kwargs: dict = {
                    "base_url": base_url,
                    "pat_token": self._pat_token,
                }
                if self._pem_file:
                    pat_kwargs["pem_file"] = self._pem_file
                await asyncio.to_thread(set_auth_token, **pat_kwargs)
            else:
                # Fallback: username/password Basic auth
                await asyncio.to_thread(
                    set_auth_token,
                    base_url=base_url,
                    username=self._username,
                    password=self._password,
                )
            self._initialized = True
            logger.info(
                "TeradataVectorBackend initialized "
                f"(host={self._host}, database={self._database}, "
                f"base_url={base_url}, "
                f"auth={'pat_token' if self._pat_token else 'user/pass'})"
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize Teradata backend: {exc}"
            ) from exc

    async def shutdown(self) -> None:
        # Disconnect SDK sessions before clearing state
        try:
            from teradatagenai import VSManager  # type: ignore[import]
            await asyncio.to_thread(VSManager.disconnect)
        except Exception as exc:
            logger.debug(f"VSManager.disconnect() during shutdown: {exc}")
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

    async def _reconnect_all(self) -> None:
        """Re-establish both SQL context and VS REST API auth.

        Uses ``_reconnect_lock`` to serialise: if another coroutine already
        reconnected after the caller's failure timestamp, the lock winner's
        fresh connection is reused (no second ``create_context()`` needed).
        """
        ts_before = time.monotonic()
        async with self._reconnect_lock:
            # Another coroutine may have reconnected while we waited for the lock.
            if self._last_reconnect_ts > ts_before:
                logger.debug("Skipping reconnect — another coroutine already reconnected")
                return

            from teradataml import create_context  # type: ignore[import]
            from teradatagenai import set_auth_token  # type: ignore[import]

            logger.info("teradataml connection lost — re-establishing create_context()")
            ctx_kwargs: dict = {"host": self._host, "username": self._username}
            if self._password:
                ctx_kwargs["password"] = self._password
            if self._database:
                ctx_kwargs["database"] = self._database
            await asyncio.to_thread(create_context, **ctx_kwargs)

            if self._pat_token:
                base_url = self._base_url
                if base_url.endswith("/open-analytics"):
                    base_url = base_url[:-len("/open-analytics")]
                pat_kwargs: dict = {"base_url": base_url, "pat_token": self._pat_token}
                if self._pem_file:
                    pat_kwargs["pem_file"] = self._pem_file
                await asyncio.to_thread(set_auth_token, **pat_kwargs)

            self._last_reconnect_ts = time.monotonic()

    @staticmethod
    def _is_connection_lost(exc: BaseException) -> bool:
        """Return True if *exc* indicates a stale / dead Teradata connection.

        Known patterns:
        - ``AttributeError: 'NoneType' object has no attribute 'cursor'``
          (teradataml global context garbage-collected after idle timeout)
        - ``OperationalError: N is not a valid connection pool handle``
          (teradatasql pool invalidated by a concurrent ``create_context()``)
        - ``OperationalError: … socket … / … connection …``
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
                or "connection" in msg
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

        try:
            return await asyncio.to_thread(execute_sql, sql)
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
            return await asyncio.to_thread(execute_sql, sql)

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

    def _get_store(self, collection_name: str) -> Any:
        """Return cached VectorStore, attaching to an existing store if not yet cached."""
        if collection_name not in self._stores:
            try:
                from teradatagenai import VectorStore  # type: ignore[import]
                vs = VectorStore(collection_name)
                self._stores[collection_name] = vs
                self._collections.add(collection_name)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to attach to existing Teradata VS '{collection_name}': {exc}"
                ) from exc
        return self._stores[collection_name]

    async def _poll_status(
        self,
        vs: Any,
        operation: str,
        timeout: int = 300,
        interval: int = 5,
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

        Resilient to ``create_context()`` calls from other code paths (e.g.
        ``_execute_sql`` reconnect) that invalidate teradataml global state.
        After 3 consecutive poll errors, re-establishes both SQL and REST API
        connections, then re-creates the ``VectorStore`` instance so status
        polling can resume.
        """
        deadline = time.monotonic() + timeout
        poll_count = 0
        consecutive_errors = 0
        last_status = ""
        collection_name = getattr(vs, "name", None) or getattr(vs, "_name", None)
        self._vs_operation_active = True

        while time.monotonic() < deadline:
            try:
                status_str = await self._get_vs_status(vs)
                consecutive_errors = 0  # reset on success

                # Log status changes and periodic heartbeats
                if status_str != last_status:
                    logger.info(f"VS '{operation}' status: {status_str}")
                    last_status = status_str
                elif poll_count % 12 == 0:  # Every ~60s at 5s interval
                    elapsed = int(time.monotonic() - (deadline - timeout))
                    logger.info(f"VS '{operation}' still {status_str} ({elapsed}s elapsed)")

                if any(kw in status_str for kw in ("COMPLETED", "READY", "SUCCESS")):
                    self._vs_operation_active = False
                    return vs
                if any(kw in status_str for kw in ("FAILED", "ERROR", "ABORTED")):
                    self._vs_operation_active = False
                    raise RuntimeError(
                        f"Teradata VS operation '{operation}' failed with status: {status_str}"
                    )
            except RuntimeError:
                self._vs_operation_active = False
                raise
            except Exception as exc:
                consecutive_errors += 1
                logger.warning(f"VS status poll error during '{operation}': {exc}")

                # After 3 consecutive failures, the global teradataml state is
                # likely stale (another code path called create_context()).
                # Re-establish connections and rebuild the VectorStore instance.
                if consecutive_errors == 3 and collection_name:
                    logger.info(
                        f"VS '{operation}': 3 consecutive poll errors — "
                        f"re-establishing connections and rebuilding VS instance"
                    )
                    try:
                        await self._reconnect_all()
                        from teradatagenai import VectorStore as _VS  # type: ignore[import]
                        vs = _VS(collection_name)
                        logger.info(f"VS '{operation}': connections restored, polling resumed")
                        consecutive_errors = 0
                    except Exception as reconn_exc:
                        logger.warning(f"VS '{operation}': reconnection failed: {reconn_exc}")

            poll_count += 1
            await asyncio.sleep(interval)
        self._vs_operation_active = False
        raise TimeoutError(
            f"Teradata VS operation '{operation}' timed out after {timeout}s "
            f"(last status: {last_status})"
        )

    @staticmethod
    async def _get_vs_status(vs: Any) -> str:
        """Extract the canonical status string from a VectorStore instance.

        Prefers ``vs.get_details(return_type='json')`` because
        ``vs.status()`` is unreliable during the creation phase — it
        returns ``None`` or raises ``TDML_2412 Object not found`` while
        the VS is in ``CREATING (PREPARING INPUT)``.

        ``get_details(return_type='json')`` returns a plain dict with a
        ``vs_status`` key that is reliable throughout the full lifecycle.

        Falls back to ``vs.status()`` only when ``get_details()`` is
        unavailable.
        """
        # Primary: get_details(return_type='json') — plain dict, reliable
        try:
            details = await asyncio.to_thread(
                lambda: vs.get_details(return_type="json")
            )
            if details and isinstance(details, dict):
                vs_status = details.get("vs_status")
                if vs_status is not None:
                    return str(vs_status).upper()
        except Exception:
            pass  # fall through to status()

        # Fallback: status() — works once the VS is past the initial phase
        try:
            status = await asyncio.to_thread(vs.status)
            if status is not None:
                # status() returns a teradataml DataFrame
                pdf = await asyncio.to_thread(status.to_pandas)
                if not pdf.empty and "status" in pdf.columns:
                    return str(pdf["status"].iloc[0]).upper()
                return str(status).upper()
        except Exception:
            pass

        return "UNKNOWN"

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
        """Destroy the VectorStore and drop the companion staging table."""
        deleted = False

        # 1. Destroy the VectorStore
        if name in self._stores:
            vs = self._stores.pop(name)
            try:
                await asyncio.to_thread(vs.destroy)
                await self._poll_status(vs, operation="destroy", timeout=120)
                deleted = True
                logger.info(f"Teradata VS '{name}' destroyed")
            except Exception as exc:
                logger.warning(f"VS destroy failed for '{name}': {exc}")

        self._collections.discard(name)

        # 2. Drop staging table
        qualified = self._qualified(self._staging_table(name))
        try:
            await self._execute_sql(f"DROP TABLE {qualified}")
            deleted = True
        except Exception as exc:
            exc_str = str(exc)
            if "3807" in exc_str or "does not exist" in exc_str.lower():
                pass  # already gone
            else:
                logger.warning(f"Failed to drop staging table '{qualified}': {exc}")

        return deleted

    async def count(self, collection_name: str) -> int:
        """Return the number of documents (staging table or chunks_table)."""
        if self._vs_operation_active:
            return 0  # Don't run SQL while VS create/add is in progress
        staging = await self._staging_count(collection_name)
        if staging:
            return staging
        # Fallback: server-side chunked collections use vectorstoreV_ table
        vs_count = await self._vs_table_count(collection_name)
        return vs_count or 0

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
        from teradataml import copy_to_sql  # type: ignore[import]
        from teradatagenai import VectorStore  # type: ignore[import]

        staging = self._staging_table(collection_name)
        staging_qualified = self._qualified(staging)
        delta_table = f"UDERIA_DELTA_{uuid4().hex[:8].upper()}"
        delta_qualified = self._qualified(delta_table)

        rows = [
            {
                "CHUNK_ID": doc.id,
                "CONTENT": doc.content,
                "METADATA_JSON": json.dumps(doc.metadata or {}),
            }
            for doc in documents
        ]
        df = pd.DataFrame(rows)

        try:
            # Write delta to a named temp table (used for incremental VS ingestion)
            await asyncio.to_thread(
                copy_to_sql,
                df=df,
                table_name=delta_table,
                schema_name=self._database,
                if_exists="replace",
                index=False,
            )

            # Append to staging table for ID tracking
            await asyncio.to_thread(
                copy_to_sql,
                df=df,
                table_name=staging,
                schema_name=self._database,
                if_exists="append",
                index=False,
            )

            if collection_name not in self._stores:
                # First add: create the VectorStore from the full staging table
                vs = VectorStore(collection_name)
                await asyncio.to_thread(
                    vs.create,
                    embeddings_model=self._embedding_model,
                    search_algorithm=self._search_algorithm,
                    top_k=self._top_k,
                    target_database=self._database,
                    object_names=staging,
                    key_columns=["CHUNK_ID"],
                    data_columns=["CONTENT"],
                )
                vs = await self._poll_status(vs, operation="create")
                self._stores[collection_name] = vs
                self._collections.add(collection_name)
                logger.info(
                    f"Teradata VS '{collection_name}' created "
                    f"from staging table with {len(documents)} documents"
                )
            else:
                # Subsequent adds: ingest only the delta into the existing VS
                vs = self._stores[collection_name]
                await asyncio.to_thread(
                    vs.add_datasets,
                    data=delta_qualified,
                    key_columns=["CHUNK_ID"],
                    data_columns=["CONTENT"],
                    update_style="MINOR",
                )
                vs = await self._poll_status(vs, operation="add_datasets")
                logger.info(
                    f"Added {len(documents)} documents to Teradata VS '{collection_name}'"
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
    ) -> int:
        """Ingest files directly via ``VectorStore.create(document_files=...)``.

        The Teradata SDK handles chunking + embedding server-side.
        Follows the Chatbot PDF pattern from VantageCloud Lake notebooks.
        """
        if not self._initialized:
            await self.initialize()

        from teradatagenai import VectorStore  # type: ignore[import]

        config = chunking_config or ServerSideChunkingConfig()
        vs = VectorStore(collection_name)

        create_kwargs: dict = {
            "embeddings_model": self._embedding_model,
            "search_algorithm": self._search_algorithm,
            "top_k": self._top_k,
            "target_database": self._database,
            "document_files": file_paths,
            "chunk_size": config.chunk_size,
            "optimized_chunking": config.optimized_chunking,
            # Required by EVS per Getting Started guide Section 7:
            "object_names": [collection_name],
            "data_columns": ["chunks"],
            "vector_column": "VectorIndex",
        }

        # Header/footer trimming — only pass when non-zero to avoid
        # sending unsupported kwargs to older SDK versions.
        if config.header_height > 0:
            create_kwargs["header_height"] = config.header_height
        if config.footer_height > 0:
            create_kwargs["footer_height"] = config.footer_height

        await asyncio.to_thread(vs.create, **create_kwargs)
        # PDF processing with Bedrock embeddings can take 15–30+ minutes
        vs = await self._poll_status(vs, operation="create_from_files", timeout=1800)

        self._stores[collection_name] = vs
        self._collections.add(collection_name)
        logger.info(
            f"Teradata VS '{collection_name}' created from {len(file_paths)} file(s) "
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

        vs = self._get_store(collection_name)
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
            await asyncio.to_thread(
                copy_to_sql,
                df=rows_df,
                table_name=del_table,
                schema_name=self._database,
                if_exists="replace",
                index=False,
            )

            # 3. Remove from the VectorStore
            await asyncio.to_thread(
                vs.delete_datasets,
                data=del_qualified,
                key_columns=["CHUNK_ID"],
                update_style="MINOR",
            )
            vs = await self._poll_status(vs, operation="delete_datasets")

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
    ) -> QueryResult:
        """Semantic similarity search via the Teradata VectorStore."""
        vs = self._get_store(collection_name)

        if where is not None:
            logger.warning(
                "TeradataVectorBackend: metadata filters in query() are not yet implemented. "
                "Results will be unfiltered. (TODO: translate MetadataFilter to staging SQL)"
            )

        try:
            result_df_raw = await asyncio.to_thread(
                vs.similarity_search,
                question=query_text,
                return_type="pandas",
            )
        except Exception as exc:
            if not self._is_connection_lost(exc):
                raise RuntimeError(
                    f"Teradata similarity_search failed for collection '{collection_name}': {exc}"
                ) from exc
            # Stale connection — reconnect and retry once.
            logger.info("teradataml connection lost during query — reconnecting")
            await self._reconnect_all()
            # Re-acquire VectorStore handle (SDK object may be invalidated)
            vs = self._get_store(collection_name)
            result_df_raw = await asyncio.to_thread(
                vs.similarity_search,
                question=query_text,
                return_type="pandas",
            )

        # Defensive: some SDK versions return a wrapper with .similar_objects
        if hasattr(result_df_raw, 'similar_objects'):
            result_df_raw = result_df_raw.similar_objects

        # Normalise column names to uppercase for consistent access across SDK versions
        result_df = result_df_raw.rename(columns=str.upper).head(n_results)

        # Locate score column (SDK may use "SCORE" or "SIMILARITY_SCORE")
        score_col = next(
            (c for c in result_df.columns if "SCORE" in c),
            None,
        )
        # Locate content column.
        # Client-side chunking uses CONTENT; server-side chunking (document_files)
        # uses FILE_SPLITS as the chunk text column.
        content_col = next(
            (c for c in result_df.columns if c in (
                "CONTENT", "FILE_SPLITS", "REV_TEXT", "TEXT", "CHUNKS",
            )),
            None,
        )
        # Locate ID column: client-side → CHUNK_ID, server-side → TD_ID
        id_col = next(
            (c for c in result_df.columns if c in ("CHUNK_ID", "TD_ID")),
            None,
        )

        docs: List[VectorDocument] = []
        distances: List[float] = []

        # Detect server-side chunking: TD_FILENAME column present, no CHUNK_ID
        is_server_side = "TD_FILENAME" in result_df.columns or "CHUNK_ID" not in result_df.columns

        for _, row in result_df.iterrows():
            doc_id = str(row[id_col]) if id_col else ""
            content = str(row[content_col]) if (content_col and include_documents) else ""
            score = float(row[score_col]) if score_col else 0.0

            # Teradata returns a similarity score (0–1, higher = more similar).
            # Convert to distance (lower = more similar) per abstraction convention.
            distance = 1.0 - score

            meta: dict = {}
            if include_metadata:
                if is_server_side:
                    # Server-side collections have no staging table.
                    # Extract metadata from the SDK result columns instead.
                    if "TD_FILENAME" in result_df.columns:
                        meta["filename"] = str(row.get("TD_FILENAME", ""))
                    if "TABLENAME" in result_df.columns:
                        meta["table_name"] = str(row.get("TABLENAME", ""))
                elif doc_id:
                    meta = await self._fetch_metadata(collection_name, doc_id)

            docs.append(VectorDocument(id=doc_id, content=content, metadata=meta))
            distances.append(distance)

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

        try:
            if ids is not None:
                safe_ids = [cid.replace("'", "''") for cid in ids]
                in_clause = ", ".join(f"'{cid}'" for cid in safe_ids)
                sql = (
                    f"SELECT CHUNK_ID, CONTENT, METADATA_JSON "
                    f"FROM {staging_qualified} "
                    f"WHERE CHUNK_ID IN ({in_clause})"
                )
            else:
                row_start = offset + 1
                row_end = (offset + limit) if limit else 2_000_000_000
                sql = (
                    f"SELECT CHUNK_ID, CONTENT, METADATA_JSON FROM ("
                    f"  SELECT CHUNK_ID, CONTENT, METADATA_JSON,"
                    f"         ROW_NUMBER() OVER (ORDER BY CHUNK_ID) AS RN"
                    f"  FROM {staging_qualified}"
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

        # ── Fallback: server-side chunked collection (chunks_table_{uuid}) ──
        chunks_qualified = await self._resolve_chunks_table(collection_name)
        if not chunks_qualified:
            return GetResult(documents=[], total_count=0)

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
