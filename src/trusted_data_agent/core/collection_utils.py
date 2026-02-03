"""
Shared utilities for collection import and export.

Extracted from rest_routes.py to be reusable by both the REST API endpoints
and the AgentPackManager. All collection import/export logic is centralized here.

Key features:
- Batched JSONL format for memory-efficient export/import of large collections
- Backward-compatible import (reads both documents.json and documents.jsonl)
- Configurable parameters for agent pack vs standalone use
"""

import json
import logging
import re
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

app_logger = logging.getLogger("quart.app")

BATCH_SIZE = 5000  # Chunks per batch for ChromaDB reads/writes


async def import_collection_from_zip(
    zip_path: Path,
    user_uuid: str,
    display_name: str | None = None,
    mcp_server_id: str | None = None,
    skip_reload: bool = False,
    populate_knowledge_docs: bool = False,
) -> dict:
    """Import a collection ZIP into Uderia.

    Supports two document formats inside the ZIP:
    - documents.json  (legacy full-load — entire collection in one JSON object)
    - documents.jsonl (batched — one JSON object per line, each up to BATCH_SIZE chunks)

    Import always processes in batches via chroma_collection.add().

    Args:
        zip_path: Path to the collection ZIP file.
        user_uuid: Owner user UUID.
        display_name: Override collection name. If None, uses metadata name + " (Imported)".
        mcp_server_id: MCP server ID for planner repositories. If None, uses
                       APP_CONFIG.CURRENT_MCP_SERVER_ID for planner repos.
        skip_reload: If True, skip retriever reload after import (caller handles it).
        populate_knowledge_docs: If True, populate knowledge_documents table
                                  (needed for knowledge repo document listing UI).

    Returns:
        {"collection_id": int, "collection_name": str, "document_count": int}

    Raises:
        ValueError: On validation errors (missing files, bad format).
        RuntimeError: On import failures (ChromaDB errors, DB errors).
    """
    import shutil
    from chromadb.utils import embedding_functions

    from trusted_data_agent.agent.rag_retriever import get_rag_retriever
    from trusted_data_agent.core.config import APP_CONFIG, APP_STATE

    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir)

    try:
        # Extract ZIP
        extract_path = temp_path / "extracted"
        extract_path.mkdir()

        with zipfile.ZipFile(zip_path, 'r') as zipf:
            zipf.extractall(extract_path)

        # Read metadata
        metadata_file = extract_path / "collection_metadata.json"
        if not metadata_file.exists():
            raise ValueError("Invalid collection ZIP: collection_metadata.json missing")

        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Validate export version
        if metadata.get('export_version') != "1.0":
            raise ValueError(f"Unsupported export version: {metadata.get('export_version')}")

        # Determine document format
        documents_jsonl = extract_path / "documents.jsonl"
        documents_json = extract_path / "documents.json"

        if not documents_jsonl.exists() and not documents_json.exists():
            raise ValueError("Invalid collection ZIP: neither documents.json nor documents.jsonl found")

        use_jsonl = documents_jsonl.exists()

        # Generate unique collection name for ChromaDB
        original_name = metadata['name']
        import uuid as _uuid
        new_collection_name = f"col_{user_uuid}_{int(time.time())}_{_uuid.uuid4().hex[:6]}"

        # Determine display name
        if display_name is None:
            final_display_name = f"{original_name} (Imported)"
        else:
            final_display_name = display_name

        # Get the RAG retriever
        retriever = get_rag_retriever()
        if not retriever:
            raise RuntimeError("RAG retriever not initialized")

        # Setup embedding function
        embedding_model = metadata.get('embedding_model', 'all-MiniLM-L6-v2')
        embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=embedding_model
        )

        # Create ChromaDB collection
        chroma_client = retriever.client
        repo_type = metadata.get('repository_type', 'knowledge')
        collection_metadata = {
            "hnsw:space": "cosine",
            "repository_type": repo_type
        }

        app_logger.info(f"Creating ChromaDB collection: {new_collection_name}")
        chroma_collection = chroma_client.create_collection(
            name=new_collection_name,
            metadata=collection_metadata,
            embedding_function=embedding_func
        )

        # Import documents (batched)
        total_added = 0
        all_metadatas_for_docs = []  # Collect for knowledge_documents population

        if use_jsonl:
            # Batched JSONL format — one batch per line
            app_logger.info(f"Importing from documents.jsonl (batched format)")
            with open(documents_jsonl, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    batch = json.loads(line)
                    batch_added = _add_batch_to_chroma(
                        chroma_collection, batch, populate_knowledge_docs, all_metadatas_for_docs
                    )
                    total_added += batch_added
                    app_logger.info(f"  Batch {line_num}: added {batch_added} documents (total: {total_added})")
        else:
            # Legacy JSON format — load and batch manually
            app_logger.info(f"Importing from documents.json (legacy format)")
            with open(documents_json, 'r') as f:
                documents_data = json.load(f)

            ids = documents_data.get('ids', [])
            documents = documents_data.get('documents', [])
            metadatas = documents_data.get('metadatas', [])
            embeddings = documents_data.get('embeddings', [])

            if ids and documents and embeddings:
                # Process in batches
                for start in range(0, len(ids), BATCH_SIZE):
                    end = min(start + BATCH_SIZE, len(ids))
                    batch = {
                        'ids': ids[start:end],
                        'documents': documents[start:end],
                        'metadatas': metadatas[start:end] if metadatas else [],
                        'embeddings': embeddings[start:end] if embeddings else [],
                    }
                    batch_added = _add_batch_to_chroma(
                        chroma_collection, batch, populate_knowledge_docs, all_metadatas_for_docs
                    )
                    total_added += batch_added

        # Verify import
        document_count = chroma_collection.count()
        app_logger.info(f"Imported collection has {document_count} documents")

        # Determine MCP server binding
        if repo_type == 'planner':
            if mcp_server_id is not None:
                assigned_mcp_server_id = mcp_server_id
            else:
                assigned_mcp_server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID
            app_logger.info(f"Associating planner collection with MCP server: {assigned_mcp_server_id}")
        else:
            assigned_mcp_server_id = None

        # Create collection in database
        from trusted_data_agent.core.collection_db import CollectionDatabase, get_collection_db

        db = CollectionDatabase()
        new_collection = {
            "name": final_display_name,
            "collection_name": new_collection_name,
            "description": metadata.get('description', ''),
            "repository_type": repo_type,
            "mcp_server_id": assigned_mcp_server_id,
            "chunking_strategy": metadata.get('chunking_strategy', 'recursive'),
            "chunk_size": metadata.get('chunk_size', 1000),
            "chunk_overlap": metadata.get('chunk_overlap', 200),
            "embedding_model": embedding_model,
            "owner_user_id": user_uuid,
            "enabled": True,
            "visibility": "private"
        }

        collection_id = db.create_collection(new_collection)

        # Populate knowledge_documents table if requested
        if populate_knowledge_docs and all_metadatas_for_docs:
            _populate_knowledge_documents(collection_id, all_metadatas_for_docs)

        # For planner repositories, update APP_STATE
        if repo_type == 'planner':
            collection_db = get_collection_db()
            imported_collection_meta = collection_db.get_collection_by_id(collection_id)
            rag_collections = APP_STATE.get("rag_collections", [])
            rag_collections.append(imported_collection_meta)
            APP_STATE["rag_collections"] = rag_collections
            app_logger.info(f"Added planner collection to APP_STATE (total: {len(rag_collections)})")

        # Reload retriever
        if not skip_reload:
            try:
                retriever.reload_collections_for_mcp_server()
                app_logger.info(f"Reloaded RAG collections after import")

                if collection_id in retriever.collections:
                    actual_count = retriever.collections[collection_id].count()
                    app_logger.info(f"Verified: collection {collection_id} has {actual_count} documents")
                    document_count = actual_count
            except Exception as e:
                app_logger.warning(f"Failed to verify import: {e}", exc_info=True)

        return {
            "collection_id": collection_id,
            "collection_name": final_display_name,
            "document_count": document_count,
        }

    except (ValueError, RuntimeError):
        raise
    except Exception as e:
        app_logger.error(f"Failed to import collection: {e}", exc_info=True)
        raise RuntimeError(f"Failed to import collection: {e}")
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def _add_batch_to_chroma(
    chroma_collection,
    batch: dict,
    collect_metadatas: bool,
    all_metadatas: list,
) -> int:
    """Add a batch of documents to ChromaDB collection.

    Returns the number of documents added.
    """
    ids = batch.get('ids', [])
    documents = batch.get('documents', [])
    metadatas = batch.get('metadatas', [])
    embeddings = batch.get('embeddings', [])

    if not ids or not documents:
        return 0

    # Sanitize metadata: ChromaDB requires flat values, no None
    if metadatas:
        for meta in metadatas:
            for key in list(meta.keys()):
                if meta[key] is None:
                    meta[key] = ""

    # Collect metadatas for knowledge_documents population
    if collect_metadatas and metadatas:
        all_metadatas.extend(metadatas)

    chroma_collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas if metadatas else None,
        embeddings=embeddings if embeddings else None,
    )

    return len(ids)


def _populate_knowledge_documents(collection_id: int, all_metadatas: list):
    """Populate the knowledge_documents table from chunk metadata."""
    from trusted_data_agent.auth.database import DATABASE_URL

    try:
        db_path = DATABASE_URL.replace('sqlite:///', '')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()

        seen_doc_ids = set()
        for meta in all_metadatas:
            doc_id = meta.get("document_id", "")
            if doc_id and doc_id not in seen_doc_ids:
                seen_doc_ids.add(doc_id)
                cursor.execute("""
                    INSERT OR IGNORE INTO knowledge_documents
                    (collection_id, document_id, filename, document_type, title,
                     author, source, category, tags, file_size, content_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    collection_id,
                    doc_id,
                    meta.get("filename", ""),
                    meta.get("document_type", "json"),
                    meta.get("title", meta.get("filename", "")),
                    meta.get("author", ""),
                    meta.get("source", "import"),
                    meta.get("category", ""),
                    meta.get("tags", ""),
                    0,
                    "",
                    now,
                ))

        conn.commit()
        conn.close()
        app_logger.info(f"Populated {len(seen_doc_ids)} knowledge documents for collection {collection_id}")

    except Exception as e:
        app_logger.warning(f"Failed to populate knowledge_documents: {e}", exc_info=True)


async def export_collection_to_zip(
    collection_id: int,
    user_uuid: str,
    output_path: Path | None = None,
) -> Path:
    """Export a collection to a ZIP file using batched JSONL format.

    Reads from ChromaDB in batches of BATCH_SIZE, writing one JSON object per line
    to documents.jsonl. Peak memory is O(BATCH_SIZE) regardless of collection size.

    Args:
        collection_id: Database collection ID.
        user_uuid: User performing the export (for ownership check).
        output_path: Directory for output. If None, uses a temp directory.

    Returns:
        Path to the created ZIP file.

    Raises:
        ValueError: Collection not found or not owned by user.
        RuntimeError: Export failure.
    """
    import shutil

    from trusted_data_agent.agent.rag_retriever import get_rag_retriever
    from trusted_data_agent.core.collection_db import CollectionDatabase

    temp_dir = tempfile.mkdtemp()
    temp_export_dir = Path(temp_dir)

    try:
        # Get collection from database
        db = CollectionDatabase()
        collection = db.get_collection_by_id(collection_id)

        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        if collection['owner_user_id'] != user_uuid:
            raise ValueError("You don't own this collection")

        # Get ChromaDB collection
        collection_name = collection['collection_name']
        retriever = get_rag_retriever()
        if not retriever:
            raise RuntimeError("RAG retriever not initialized")

        chroma_collection = None
        try:
            chroma_collection = retriever.client.get_collection(name=collection_name)
        except Exception as e:
            raise ValueError(f"ChromaDB collection not found: {e}")

        # Get document count
        total_count = chroma_collection.count()
        app_logger.info(f"Export: Collection {collection_id} has {total_count} documents")

        # Build collection metadata
        metadata = {
            "collection_id": collection_id,
            "name": collection['name'],
            "description": collection['description'],
            "repository_type": collection['repository_type'],
            "mcp_server_id": collection.get('mcp_server_id'),
            "chunking_strategy": collection['chunking_strategy'],
            "chunk_size": collection['chunk_size'],
            "chunk_overlap": collection['chunk_overlap'],
            "embedding_model": collection['embedding_model'],
            "collection_name": collection_name,
            "document_count": total_count,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "export_version": "1.0"
        }

        metadata_file = temp_export_dir / "collection_metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        # Export documents in batched JSONL format
        documents_file = temp_export_dir / "documents.jsonl"

        with open(documents_file, 'w') as f:
            offset = 0
            batch_num = 0
            while offset < total_count:
                batch_data = chroma_collection.get(
                    offset=offset,
                    limit=BATCH_SIZE,
                    include=['embeddings', 'documents', 'metadatas']
                )

                if not batch_data['ids']:
                    break

                # Convert embeddings to lists if needed
                embeddings_list = []
                for emb in batch_data['embeddings']:
                    if isinstance(emb, list):
                        embeddings_list.append(emb)
                    else:
                        embeddings_list.append(emb.tolist() if hasattr(emb, 'tolist') else list(emb))

                batch_obj = {
                    'ids': batch_data['ids'],
                    'documents': batch_data['documents'],
                    'metadatas': batch_data['metadatas'],
                    'embeddings': embeddings_list,
                }

                f.write(json.dumps(batch_obj, allow_nan=False) + '\n')
                batch_num += 1
                offset += len(batch_data['ids'])
                app_logger.info(f"Export: Wrote batch {batch_num} ({offset}/{total_count} documents)")

        # Create ZIP file
        safe_name = re.sub(r'[<>:"/\\|?*]', '-', collection['name'])
        safe_name = safe_name.replace(' ', '_')
        safe_name = safe_name.strip('-_')
        zip_filename = f"collection_{collection_id}_{safe_name}.zip"

        if output_path:
            output_dir = Path(output_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            zip_path = output_dir / zip_filename
        else:
            zip_path = temp_export_dir / zip_filename

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in temp_export_dir.rglob('*'):
                if file_path.is_file() and file_path != zip_path:
                    arcname = file_path.relative_to(temp_export_dir)
                    zipf.write(file_path, arcname)

        zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
        app_logger.info(f"Exported collection {collection_id} to {zip_filename} ({zip_size_mb:.2f} MB)")

        return zip_path

    except (ValueError, RuntimeError):
        raise
    except Exception as e:
        app_logger.error(f"Error exporting collection: {e}", exc_info=True)
        raise RuntimeError(f"Failed to export collection: {e}")
