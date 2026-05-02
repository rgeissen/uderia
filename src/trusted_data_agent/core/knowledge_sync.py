"""
Knowledge Repository CDC Sync

Provides proactive staleness detection and re-embedding for knowledge documents
that have a source_uri configured. Called by:

  • POST /v1/knowledge/repositories/{id}/sync    (manual trigger via API)
  • POST /v1/knowledge/repositories/{id}/reindex (full re-embed via API)
  • Task Scheduler (when a scheduled knowledge-sync task fires)

Entry points:
  sync_knowledge_collection()   — hash-check CDC sync for source_uri docs
  reindex_knowledge_collection() — force re-embed all docs with new model

Source URI routing is handled by fetch_source() which dispatches to a
scheme-specific resolver. Currently supported schemes:
  file://   — local filesystem
  https://  — HTTP GET with conditional request (ETag / Last-Modified)
  http://   — same as https
  gdrive:// — Google Drive via existing platform connector

New schemes are added by registering a coroutine in SOURCE_RESOLVERS.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("quart.app")


# ---------------------------------------------------------------------------
# Source resolvers
# ---------------------------------------------------------------------------

async def _fetch_local_file(uri: str, user_uuid: str, source_root: str = None) -> bytes:
    """Read a local file.

    Supports two URI forms:
      - Absolute: file:///absolute/path/to/file  (path starts with /)
      - Relative: file://docs/Architecture/foo.md (no leading /)

    Relative paths are resolved against (in priority order):
      1. source_root argument (per-collection setting from Platform Jobs UI)
      2. UDERIA_DOCS_ROOT environment variable
      3. Auto-detected installation root (4 levels above this module)
    """
    import asyncio, os
    from pathlib import Path

    path = uri.replace("file://", "")

    # Relative path: no leading / and not a Windows absolute path (C:\...)
    if not path.startswith("/") and not (len(path) > 1 and path[1] == ":"):
        root = (
            source_root
            or os.environ.get("UDERIA_DOCS_ROOT")
            or str(Path(__file__).resolve().parents[3])
        )
        path = str(Path(root) / path)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: open(path, "rb").read())


async def _fetch_http(uri: str, user_uuid: str) -> bytes:
    """HTTP/HTTPS GET. Uses aiohttp if available, falls back to urllib."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(uri, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                resp.raise_for_status()
                return await resp.read()
    except ImportError:
        import asyncio, urllib.request
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(uri, timeout=60).read()
        )


async def _fetch_google_drive(uri: str, user_uuid: str) -> bytes:
    """
    Fetch a Google Drive file via the platform connector.
    URI format: gdrive://<file_id>

    Requires the Google connector to be configured and the user to have
    connected their account (messaging_identities row present).
    """
    try:
        from trusted_data_agent.connectors.google_connector import GoogleConnector
        connector = GoogleConnector()
        tokens = await connector.get_tokens(user_uuid)
        if not tokens:
            raise ValueError(
                "Google account not connected. Visit Platform Components → Connectors "
                "to link your Google account before enabling gdrive:// sync."
            )
        file_id = uri.replace("gdrive://", "").strip("/")

        import aiohttp
        access_token = tokens.get("access_token")
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                download_url,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                resp.raise_for_status()
                return await resp.read()
    except ImportError:
        raise RuntimeError(
            "Google Drive sync requires the aiohttp package. "
            "Install it with: pip install aiohttp"
        )


SOURCE_RESOLVERS = {
    "file":   _fetch_local_file,
    "https":  _fetch_http,
    "http":   _fetch_http,
    "gdrive": _fetch_google_drive,
}


async def fetch_source(source_uri: str, user_uuid: str, source_root: str = None) -> bytes:
    """
    Fetch content bytes from a source URI.
    Dispatches to the appropriate resolver based on URI scheme.

    source_root is only used for file:// URIs with relative paths — it sets the
    base directory for resolution (see _fetch_local_file for priority order).

    Raises:
        ValueError  — unsupported scheme or missing credentials
        RuntimeError — connector not available
    """
    if not source_uri:
        raise ValueError("source_uri is empty")

    scheme = source_uri.split("://")[0].lower()
    if not SOURCE_RESOLVERS.get(scheme):
        raise ValueError(
            f"Unsupported source URI scheme '{scheme}'. "
            f"Supported: {', '.join(SOURCE_RESOLVERS.keys())}"
        )

    if scheme == "file":
        return await _fetch_local_file(source_uri, user_uuid, source_root)
    return await SOURCE_RESOLVERS[scheme](source_uri, user_uuid)


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------

async def sync_knowledge_collection(
    collection_id: int,
    user_uuid: str,
    older_than_seconds: int = 3600,
) -> dict:
    """
    Re-sync all sync-enabled documents in a collection whose source has
    potentially changed (last_checked_at older than older_than_seconds).

    For each candidate document:
      1. Fetch content from source_uri
      2. Hash-check — skip if content unchanged
      3. Call _upsert_document() (via knowledge_routes) to re-embed

    Returns:
        {
            "checked":          int,
            "updated":          int,
            "unchanged":        int,
            "errors":           int,
            "duration_seconds": float,
        }
    """
    from trusted_data_agent.core.collection_db import get_collection_db

    db = get_collection_db()
    collection = db.get_collection_by_id(collection_id)
    if not collection:
        raise ValueError(f"Collection {collection_id} not found")

    candidates = db.get_sync_candidates(collection_id, older_than_seconds=older_than_seconds)
    results: dict = defaultdict(int)
    results["updated_files"] = []
    start = time.monotonic()
    source_root = collection.get("source_root") or None

    logger.info(
        f"[CDC SYNC] collection={collection_id} candidates={len(candidates)} "
        f"interval={collection.get('sync_interval', 'daily')} "
        f"source_root={source_root or '(auto)'}"
    )

    for doc in candidates:
        results["checked"] += 1
        doc_id = doc["document_id"]
        filename = doc["filename"]
        source_uri = doc.get("source_uri")

        if not source_uri:
            db.mark_document_checked(doc_id)
            results["unchanged"] += 1
            continue

        try:
            content_bytes = await fetch_source(source_uri, user_uuid, source_root=source_root)
        except Exception as fetch_err:
            logger.warning(
                f"[CDC SYNC] Fetch failed for '{filename}' "
                f"(doc={doc_id}): {fetch_err}"
            )
            results["errors"] += 1
            continue

        # Hash check — mark checked and skip if content identical
        import hashlib
        new_hash = hashlib.sha256(content_bytes).hexdigest()
        if doc.get("content_hash") == new_hash:
            db.mark_document_checked(doc_id)
            results["unchanged"] += 1
            logger.debug(f"[CDC SYNC] '{filename}' unchanged (doc={doc_id})")
            continue

        # Content changed — re-ingest via the same pipeline as manual upload
        try:
            await _sync_upsert_document(
                collection_id=collection_id,
                collection=collection,
                content_bytes=content_bytes,
                content_hash=new_hash,
                existing_doc=doc,
                user_uuid=user_uuid,
            )
            results["updated"] += 1
            results["updated_files"].append(filename)
            logger.info(f"[CDC SYNC] '{filename}' updated (doc={doc_id})")
        except Exception as upsert_err:
            logger.error(
                f"[CDC SYNC] Re-ingest failed for '{filename}' "
                f"(doc={doc_id}): {upsert_err}",
                exc_info=True,
            )
            results["errors"] += 1

    duration = round(time.monotonic() - start, 2)
    results["duration_seconds"] = duration

    logger.info(
        f"[CDC SYNC] collection={collection_id} done — "
        f"checked={results['checked']} updated={results['updated']} "
        f"unchanged={results['unchanged']} errors={results['errors']} "
        f"duration={duration}s"
    )
    return dict(results)


async def _sync_upsert_document(
    collection_id: int,
    collection: dict,
    content_bytes: bytes,
    content_hash: str,
    existing_doc: dict,
    user_uuid: str,
) -> None:
    """
    Re-embed a document that has changed at its source.
    Mirrors the client-side chunking path in knowledge_routes.py but runs
    without an HTTP request context (called from scheduler or sync endpoint).

    Server-side chunking (Teradata EVS) is handled by delete → re-submit.
    Client-side chunking uses ingest_epoch generation cleanup.
    """
    import os, tempfile
    from trusted_data_agent.core.collection_db import get_collection_db
    from trusted_data_agent.agent.rag_retriever import get_rag_retriever
    from trusted_data_agent.agent.repository_constructor import (
        create_repository_constructor, RepositoryType, ChunkingStrategy
    )
    from trusted_data_agent.vectorstore.types import ServerSideChunkingConfig
    from trusted_data_agent.vectorstore.capabilities import VectorStoreCapability

    db = get_collection_db()
    retriever = get_rag_retriever()
    if not retriever:
        raise RuntimeError("RAG retriever not initialized")

    collection_name = collection["collection_name"]
    chunking_strategy_str = collection.get("chunking_strategy", "paragraph")
    embedding_model = collection.get("embedding_model", "all-MiniLM-L6-v2")
    chunk_size = collection.get("chunk_size", 1000)
    chunk_overlap = collection.get("chunk_overlap", 200)
    filename = existing_doc["filename"]
    doc_id = existing_doc["document_id"]
    ingest_epoch = int(time.time())

    backend = await retriever._get_knowledge_backend(collection_id)
    if not backend:
        raise RuntimeError(f"No backend available for collection {collection_id}")

    # Write content to a temp file (needed by both paths)
    suffix = os.path.splitext(filename)[1] or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        tf.write(content_bytes)
        temp_path = tf.name

    try:
        if chunking_strategy_str == "server_side" and backend.has_capability(
            VectorStoreCapability.SERVER_SIDE_CHUNKING
        ):
            # ── Server-side path: delete existing doc then re-submit ──────
            try:
                await backend.delete_document(collection_name, doc_id)
            except Exception:
                pass  # doc may not exist yet; non-fatal

            await backend.add_document_files(
                collection_name=collection_name,
                file_paths=[temp_path],
                chunking_config=ServerSideChunkingConfig(
                    optimized_chunking=bool(collection.get("optimized_chunking", 1)),
                    chunk_size=collection.get("ss_chunk_size", 2000),
                    header_height=collection.get("header_height", 0),
                    footer_height=collection.get("footer_height", 0),
                ),
            )
            chunk_count = 0  # deferred
        else:
            # ── Client-side path: chunk → embed → upsert → cleanup ────────
            from trusted_data_agent.llm.document_upload import DocumentUploadHandler
            doc_handler = DocumentUploadHandler()
            prepared = doc_handler.prepare_document_for_llm(
                file_path=temp_path,
                provider_name="Ollama",
                model_name="",
                effective_config={"enabled": True, "use_native_upload": False},
            )
            content_text = prepared.get("content", "")
            if not content_text:
                raise ValueError(f"Failed to extract text from '{filename}'")

            try:
                cs = ChunkingStrategy[chunking_strategy_str.upper()]
            except KeyError:
                cs = ChunkingStrategy.PARAGRAPH

            constructor = create_repository_constructor(
                repository_type=RepositoryType.KNOWLEDGE,
                chroma_client=retriever.client,
                storage_dir=retriever.rag_cases_dir / f"collection_{collection_id}",
                embedding_model=embedding_model,
                chunking_strategy=cs,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                backend=backend,
            )

            result = await constructor.construct_async(
                collection_id=collection_id,
                content=content_text,
                collection_name=collection_name,
                filename=filename,
                document_id=doc_id,
                ingest_epoch=ingest_epoch,
                save_original=False,
            )
            chunk_count = result.get("chunks_stored", 0)

            # Stale chunk cleanup
            try:
                from trusted_data_agent.vectorstore.filters import FieldFilter, AndFilter, FilterOp
                stale_filter = AndFilter([
                    FieldFilter("document_id", FilterOp.EQ, doc_id),
                    FieldFilter("ingest_epoch", FilterOp.LT, ingest_epoch),
                ])
                stale_result = await backend.get(
                    collection_name,
                    where=stale_filter,
                    include_documents=False,
                    include_metadata=False,
                    limit=10_000,
                )
                stale_ids = [d.id for d in stale_result.documents] if stale_result and stale_result.documents else []
                if stale_ids:
                    await backend.delete(collection_name, ids=stale_ids)
                    logger.info(
                        f"[CDC SYNC] Removed {len(stale_ids)} stale chunks "
                        f"for '{filename}' (doc={doc_id})"
                    )
            except Exception as ce:
                logger.warning(f"[CDC SYNC] Stale chunk cleanup failed: {ce}")

        # Persist updated metadata
        db.upsert_document_metadata(
            document_id=doc_id,
            collection_id=collection_id,
            filename=filename,
            content_hash=content_hash,
            ingest_epoch=ingest_epoch,
            chunk_count=chunk_count,
            source_uri=existing_doc.get("source_uri"),
            sync_enabled=existing_doc.get("sync_enabled", 1),
            document_type=existing_doc.get("document_type", ""),
            title=existing_doc.get("title", filename),
            author=existing_doc.get("author", ""),
            source="sync",
            category=existing_doc.get("category", ""),
            tags=existing_doc.get("tags", ""),
            file_size=len(content_bytes),
        )
        db.sync_collection_counts(collection_id)

    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Full re-index (embedding model change or forced refresh)
# ---------------------------------------------------------------------------

async def reindex_knowledge_collection(
    collection_id: int,
    user_uuid: str,
    strategy: str = "in_place",
) -> dict:
    """
    Force re-embed every document in a collection regardless of content hash.

    Two strategies:
        in_place   — re-ingest each document over the same collection_name.
                     Used when subscribers or marketplace listing exist.
        shadow_swap — (reserved) create a shadow collection, swap on success.
                     Currently falls back to in_place (both strategies share
                     the same ingest path; shadow_swap isolation is a future
                     enhancement).

    For each document:
      1. Locate original bytes from source_uri (or skip if no source_uri)
      2. Force-ingest (hash ignored — always re-embeds)
      3. Cleanup stale chunks with old ingest_epoch

    After all documents: lock the embedding model by setting
    embedding_model_locked=1 on the collection.

    Returns:
        {
            "strategy":         str,
            "reindexed":        int,
            "skipped":          int,
            "errors":           int,
            "duration_seconds": float,
        }
    """
    from trusted_data_agent.core.collection_db import get_collection_db

    db = get_collection_db()
    collection = db.get_collection_by_id(collection_id)
    if not collection:
        raise ValueError(f"Collection {collection_id} not found")

    documents = db.get_all_documents_in_collection(collection_id)
    start = time.monotonic()
    results: dict = defaultdict(int)
    results["strategy"] = strategy
    source_root = collection.get("source_root") or None

    logger.info(
        f"[REINDEX] collection={collection_id} strategy={strategy} "
        f"documents={len(documents)} source_root={source_root or '(auto)'}"
    )

    for doc in documents:
        doc_id = doc["document_id"]
        filename = doc["filename"]
        source_uri = doc.get("source_uri")

        if not source_uri:
            logger.debug(f"[REINDEX] '{filename}' has no source_uri — skipping")
            results["skipped"] += 1
            continue

        try:
            content_bytes = await fetch_source(source_uri, user_uuid, source_root=source_root)
        except Exception as fetch_err:
            logger.warning(
                f"[REINDEX] Fetch failed for '{filename}' "
                f"(doc={doc_id}): {fetch_err}"
            )
            results["errors"] += 1
            continue

        import hashlib
        new_hash = hashlib.sha256(content_bytes).hexdigest()

        try:
            await _sync_upsert_document(
                collection_id=collection_id,
                collection=collection,
                content_bytes=content_bytes,
                content_hash=new_hash,
                existing_doc=doc,
                user_uuid=user_uuid,
            )
            results["reindexed"] += 1
            logger.info(f"[REINDEX] '{filename}' re-indexed (doc={doc_id})")
        except Exception as upsert_err:
            logger.error(
                f"[REINDEX] Re-embed failed for '{filename}' "
                f"(doc={doc_id}): {upsert_err}",
                exc_info=True,
            )
            results["errors"] += 1

    # Lock the embedding model so mismatch warnings stop appearing
    try:
        db.update_collection(collection_id, {"embedding_model_locked": 1})
        logger.info(f"[REINDEX] collection={collection_id} embedding_model_locked=1")
    except Exception as lock_err:
        logger.warning(f"[REINDEX] Failed to lock embedding model: {lock_err}")

    duration = round(time.monotonic() - start, 2)
    results["duration_seconds"] = duration

    logger.info(
        f"[REINDEX] collection={collection_id} done — "
        f"reindexed={results['reindexed']} skipped={results['skipped']} "
        f"errors={results['errors']} duration={duration}s"
    )
    return dict(results)
