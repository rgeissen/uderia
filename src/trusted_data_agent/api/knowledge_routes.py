"""
Knowledge Repository REST API Endpoints

Provides endpoints for creating and managing Knowledge repositories.
Follows the same patterns as Planner repositories but with document-centric operations.

Endpoints:
- POST /v1/knowledge/repositories/{collection_id}/documents - Upload document to Knowledge repository
- GET /v1/knowledge/repositories/{collection_id}/documents - List documents in repository
- GET /v1/knowledge/repositories/{collection_id}/documents/{document_id} - Get document details
- DELETE /v1/knowledge/repositories/{collection_id}/documents/{document_id} - Delete document
- POST /v1/knowledge/repositories/{collection_id}/search - Search within Knowledge repository
"""

import os
import logging
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
from quart import Blueprint, request, jsonify, Response
import hashlib
import asyncio
import json

from trusted_data_agent.core.config import APP_STATE
from trusted_data_agent.auth.middleware import require_auth
from trusted_data_agent.agent.rag_retriever import get_rag_retriever
from trusted_data_agent.llm.document_upload import DocumentUploadHandler
from trusted_data_agent.agent.repository_constructor import (
    create_repository_constructor,
    RepositoryType,
    ChunkingStrategy
)
from trusted_data_agent.vectorstore.capabilities import VectorStoreCapability
from trusted_data_agent.vectorstore.types import ServerSideChunkingConfig

# Create blueprint
knowledge_api_bp = Blueprint('knowledge_api', __name__)

app_logger = logging.getLogger('tda')


@knowledge_api_bp.route("/v1/knowledge/preview-chunking", methods=["POST"])
@require_auth
async def preview_document_chunking(current_user: dict):
    """
    Preview how a document will be chunked without storing it.
    
    This endpoint allows users to experiment with different chunking strategies
    before committing to creating a Knowledge repository.
    
    Multipart Form Data:
        - file: Document file (PDF, TXT, DOCX, MD)
        - chunking_strategy: Chunking strategy (fixed_size, paragraph, sentence, semantic)
        - chunk_size: Size of chunks in characters (default: 1000)
        - chunk_overlap: Overlap between chunks (default: 200)
    
    Returns:
        JSON with chunks array containing text segments
    """
    try:
        # Get uploaded file
        files = await request.files
        if 'file' not in files:
            return jsonify({"status": "error", "message": "No file provided"}), 400
        
        file = files['file']
        if not file or not file.filename:
            return jsonify({"status": "error", "message": "Invalid file"}), 400
        
        # Get form parameters
        form = await request.form
        chunking_strategy_str = form.get('chunking_strategy', 'semantic')
        chunk_size = int(form.get('chunk_size', 1000))
        chunk_overlap = int(form.get('chunk_overlap', 200))
        
        # Validate chunking strategy
        try:
            chunking_strategy = ChunkingStrategy[chunking_strategy_str.upper()]
        except KeyError:
            return jsonify({
                "status": "error",
                "message": f"Invalid chunking_strategy: {chunking_strategy_str}. Valid options: fixed_size, paragraph, sentence, semantic"
            }), 400
        
        # Save file temporarily
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1])
        file_content = file.read()
        temp_file.write(file_content)
        temp_file.flush()
        temp_file.close()
        
        try:
            # Extract text from document - optimized for preview
            file_extension = os.path.splitext(temp_file.name)[1].lower()
            
            # Fast extraction for preview - limit PDF to first 20 pages
            if file_extension == '.pdf':
                try:
                    from PyPDF2 import PdfReader
                    with open(temp_file.name, 'rb') as f:
                        pdf_reader = PdfReader(f)
                        # Only extract first 20 pages for instant preview
                        max_pages = min(20, len(pdf_reader.pages))
                        pages_text = [pdf_reader.pages[i].extract_text() for i in range(max_pages)]
                        # Join with double newline to preserve paragraph boundaries
                        document_text = "\n\n".join(pages_text)
                        is_preview_truncated = len(pdf_reader.pages) > max_pages
                except Exception as e:
                    return jsonify({"status": "error", "message": f"PDF extraction failed: {str(e)}"}), 400
            else:
                # For non-PDF, use standard extraction
                doc_handler = DocumentUploadHandler()
                extracted = doc_handler._extract_text_from_document(temp_file.name)
                document_text = extracted.get('content', '')
                is_preview_truncated = False
            
            if not document_text:
                return jsonify({
                    "status": "error",
                    "message": "No text content extracted from document"
                }), 400
            
            # Limit to reasonable size for preview (50K chars)
            preview_text = document_text[:50000] if len(document_text) > 50000 else document_text
            if len(document_text) > 50000:
                is_preview_truncated = True
            
            # Create document processor to chunk the document
            from trusted_data_agent.agent.repository_constructor import DocumentProcessor
            doc_processor = DocumentProcessor(
                chunking_strategy=chunking_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
            # Chunk the preview text
            metadata = {"filename": file.filename, "source": "preview"}
            chunk_objects = doc_processor.process_document(preview_text, metadata)
            
            # Format chunks for preview
            preview_chunks = [
                {
                    "text": chunk.content,
                    "length": len(chunk.content),
                    "index": chunk.chunk_index
                }
                for chunk in chunk_objects
            ]
            
            return jsonify({
                "status": "success",
                "chunks": preview_chunks,
                "total_chunks": len(preview_chunks),
                "total_characters": len(preview_text),
                "full_document_characters": len(document_text),
                "is_preview_truncated": is_preview_truncated,
                "average_chunk_size": len(preview_text) // len(preview_chunks) if preview_chunks else 0,
                "chunking_strategy": chunking_strategy_str,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "preview_note": "Showing first 20 pages" if is_preview_truncated and file_extension == '.pdf' else None
            }), 200
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
                
    except Exception as e:
        app_logger.error(f"[Knowledge Preview] Error: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


async def upload_knowledge_document_stream(current_user: dict, collection_id: int):
    """
    Upload a document to a Knowledge repository with SSE progress updates.
    This version streams progress updates to prevent SSE timeout on slow servers.
    """
    # Extract ALL request data BEFORE starting the generator (must be in request context)
    files = await request.files
    if 'file' not in files:
        return jsonify({"status": "error", "message": "No file provided"}), 400
    
    file = files['file']
    if not file or not file.filename:
        return jsonify({"status": "error", "message": "Invalid file"}), 400
    
    # Read file content now
    file_content = file.read()
    filename = file.filename
    
    # Get all form parameters now
    form = await request.form
    title = form.get('title', filename)
    author = form.get('author', '')
    category = form.get('category', '')
    tags_str = form.get('tags', '')
    tags = [t.strip() for t in tags_str.split(',') if t.strip()]
    
    chunking_strategy_str = form.get('chunking_strategy', 'semantic')
    chunk_size = int(form.get('chunk_size', 1000))
    chunk_overlap = int(form.get('chunk_overlap', 200))
    embedding_model = form.get('embedding_model', 'all-MiniLM-L6-v2')
    
    def format_sse(data: dict, event: str = "message") -> str:
        """Format data as Server-Sent Event."""
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"
    
    async def generate_upload_stream():
        """Generator function that yields SSE progress updates."""
        progress_queue = asyncio.Queue()
        
        async def progress_callback(message: str, percentage: int):
            """Callback to report progress during upload."""
            await progress_queue.put(format_sse({
                "type": "progress",
                "message": message,
                "percentage": percentage
            }, "progress"))
        
        try:
            # Send initial progress
            yield format_sse({"type": "start", "message": "Starting upload..."}, "progress")
            
            # Query collection from database
            from trusted_data_agent.core.collection_db import CollectionDatabase
            db = CollectionDatabase()
            conn = db._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT collection_name, repository_type, owner_user_id, chunking_strategy, 
                       chunk_size, chunk_overlap
                FROM collections WHERE id = ?
            """, (collection_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                yield format_sse({"type": "error", "message": f"Collection {collection_id} not found"}, "error")
                return
            
            collection_name = result['collection_name']
            repository_type = result['repository_type']
            owner_user_id = result['owner_user_id']
            
            if repository_type != 'knowledge':
                yield format_sse({"type": "error", "message": f"Collection {collection_id} is not a Knowledge repository"}, "error")
                return
            
            user_id = current_user.id
            if owner_user_id != user_id:
                yield format_sse({"type": "error", "message": "Access denied"}, "error")
                return
            
            # Get retriever instance
            retriever = get_rag_retriever()
            if not retriever:
                yield format_sse({"type": "error", "message": "RAG retriever not initialized"}, "error")
                return
            
            # Save file temporarily (needed by both client-side and server-side paths)
            yield format_sse({"type": "progress", "message": "Saving file...", "percentage": 2}, "progress")

            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
            temp_file.write(file_content)
            temp_file.flush()
            temp_file.close()

            # Calculate file hash
            content_hash = hashlib.sha256(file_content).hexdigest()

            # ── Server-side chunking path (streaming) ─────────────────────────
            # Pass the raw file to the backend SDK — skip text extraction &
            # local chunking entirely.
            if chunking_strategy_str == "server_side":
                backend = await retriever._get_knowledge_backend(collection_id)

                if not backend or not backend.has_capability(VectorStoreCapability.SERVER_SIDE_CHUNKING):
                    yield format_sse({
                        "type": "error",
                        "message": "Selected backend does not support server-side chunking."
                    }, "error")
                    os.unlink(temp_file.name)
                    return

                document_id = str(uuid4())

                yield format_sse({
                    "type": "progress",
                    "message": "Uploading file to Teradata for server-side chunking & embedding...",
                    "percentage": 10
                }, "progress")

                # Run server-side chunking as a background task.
                # The progress_callback feeds real EVS status phases into
                # the queue so we can relay them as SSE events.
                import asyncio as _asyncio
                progress_queue = _asyncio.Queue()

                def _on_ingest_progress(update):
                    progress_queue.put_nowait(update)

                ingest_task = _asyncio.create_task(
                    backend.add_document_files(
                        collection_name=collection_name,
                        file_paths=[temp_file.name],
                        chunking_config=ServerSideChunkingConfig(
                            optimized_chunking=form.get("optimized_chunking", "true").lower() == "true",
                            chunk_size=int(form.get("chunk_size", 500)),
                            header_height=float(form.get("header_height", 0.0)),
                            footer_height=float(form.get("footer_height", 0.0)),
                        ),
                        progress_callback=_on_ingest_progress,
                    )
                )

                last_pct = 10
                while not ingest_task.done():
                    try:
                        update = await _asyncio.wait_for(progress_queue.get(), timeout=10)
                        pct = max(update.percentage, last_pct)  # never go backwards
                        last_pct = pct
                        minutes = update.elapsed_seconds // 60
                        seconds = update.elapsed_seconds % 60
                        time_str = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
                        yield format_sse({
                            "type": "progress",
                            "message": f"{update.phase} ({time_str} elapsed)",
                            "percentage": pct
                        }, "progress")
                    except _asyncio.TimeoutError:
                        continue  # no status update in 10s — keep waiting

                # Retrieve result — raises if the task failed
                try:
                    await ingest_task
                except Exception as ingest_err:
                    # Clean up the failed EVS object on Teradata so it
                    # doesn't leave a ghost dictionary entry.
                    try:
                        await backend.delete_collection(collection_name)
                        app_logger.info(f"Cleaned up failed VS '{collection_name}' on Teradata")
                    except Exception as cleanup_err:
                        app_logger.warning(
                            f"Could not clean up failed VS '{collection_name}': {cleanup_err}"
                        )

                    # If this was the first upload (no documents yet), remove
                    # the orphaned local collection record — an empty knowledge
                    # repo with no backend VS is useless.
                    try:
                        from trusted_data_agent.core.collection_db import CollectionDatabase
                        _cleanup_db = CollectionDatabase()
                        _cleanup_conn = _cleanup_db._get_connection()
                        _cleanup_cur = _cleanup_conn.cursor()
                        _cleanup_cur.execute(
                            "SELECT COUNT(*) as cnt FROM knowledge_documents WHERE collection_id = ?",
                            (collection_id,),
                        )
                        doc_count = _cleanup_cur.fetchone()["cnt"]
                        _cleanup_conn.close()
                        if doc_count == 0:
                            from trusted_data_agent.core.collection_db import get_collection_db
                            get_collection_db().delete_collection(collection_id)
                            app_logger.info(
                                f"Removed empty orphaned collection {collection_id} "
                                f"('{collection_name}')"
                            )
                    except Exception as local_err:
                        app_logger.warning(
                            f"Could not clean up local collection {collection_id}: {local_err}"
                        )

                    yield format_sse({
                        "type": "error",
                        "message": f"Server-side chunking failed: {ingest_err}"
                    }, "error")
                    os.unlink(temp_file.name)
                    return

                # Store document metadata
                from trusted_data_agent.core.collection_db import CollectionDatabase
                db = CollectionDatabase()
                conn = db._get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO knowledge_documents
                    (collection_id, document_id, filename, document_type, title, author,
                     source, category, tags, file_size, content_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    collection_id, document_id, filename,
                    os.path.splitext(filename)[1].lstrip('.'), title, author,
                    'upload', category, ','.join(tags),
                    len(file_content), content_hash,
                    datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
                conn.close()

                os.unlink(temp_file.name)

                yield format_sse({
                    "type": "complete",
                    "status": "success",
                    "message": f"Document '{filename}' ingested via server-side chunking",
                    "document_id": document_id,
                    "chunks_stored": 0,
                    "chunking_mode": "server_side",
                }, "complete")
                return

            # ── Client-side chunking path ─────────────────────────────────────
            # Validate chunking strategy
            try:
                chunking_strategy = ChunkingStrategy[chunking_strategy_str.upper()]
            except KeyError:
                yield format_sse({"type": "error", "message": f"Invalid chunking_strategy: {chunking_strategy_str}"}, "error")
                os.unlink(temp_file.name)
                return

            # Process document
            yield format_sse({"type": "progress", "message": "Extracting text from document...", "percentage": 3}, "progress")

            doc_handler = DocumentUploadHandler()
            prepared_doc = doc_handler.prepare_document_for_llm(
                file_path=temp_file.name,
                provider_name="Ollama",
                model_name="",
                effective_config={"enabled": True, "use_native_upload": False}
            )

            if 'content' not in prepared_doc or not prepared_doc['content']:
                yield format_sse({"type": "error", "message": "Failed to extract text from document"}, "error")
                os.unlink(temp_file.name)
                return

            document_content = prepared_doc['content']

            # Create repository constructor (backend-abstracted path)
            backend = await retriever._get_knowledge_backend(collection_id)
            constructor = create_repository_constructor(
                repository_type=RepositoryType.KNOWLEDGE,
                chroma_client=retriever.client,
                storage_dir=retriever.rag_cases_dir / f"collection_{collection_id}",
                embedding_model=embedding_model,
                chunking_strategy=chunking_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                backend=backend,
            )

            # Construct repository entry with progress updates
            result = await constructor.construct_async(
                collection_id=collection_id,
                content=document_content,
                collection_name=collection_name,
                filename=filename,
                document_type=os.path.splitext(filename)[1].lstrip('.'),
                title=title,
                author=author,
                category=category,
                tags=tags,
                source='upload',
                file_size=len(file_content),
                content_hash=content_hash,
                save_original=True,
                progress_callback=progress_callback
            )

            # Drain any remaining progress messages
            while not progress_queue.empty():
                try:
                    progress_msg = progress_queue.get_nowait()
                    yield progress_msg
                except asyncio.QueueEmpty:
                    break

            # Clean up temp file
            os.unlink(temp_file.name)

            if result['status'] == 'success':
                # Store metadata in database (same as original)
                from trusted_data_agent.core.collection_db import CollectionDatabase
                db = CollectionDatabase()

                doc_data = {
                    'collection_id': collection_id,
                    'document_id': result['metadata']['document_id'],
                    'filename': filename,
                    'document_type': result['metadata']['document_type'],
                    'title': title,
                    'author': author,
                    'source': 'upload',
                    'category': category,
                    'tags': tags,
                    'file_size': len(file_content),
                    'content_hash': content_hash,
                    'created_at': datetime.now(timezone.utc).isoformat()
                }

                conn = db._get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO knowledge_documents
                    (collection_id, document_id, filename, document_type, title, author,
                     source, category, tags, file_size, content_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_data['collection_id'], doc_data['document_id'], doc_data['filename'],
                    doc_data['document_type'], doc_data['title'], doc_data['author'],
                    doc_data['source'], doc_data['category'], ','.join(doc_data['tags']),
                    doc_data['file_size'], doc_data['content_hash'], doc_data['created_at']
                ))
                conn.commit()
                conn.close()

                yield format_sse({
                    "type": "complete",
                    "status": "success",
                    "message": f"Successfully uploaded {filename}",
                    "document_id": result['metadata']['document_id'],
                    "chunks_stored": result.get('chunks_stored', 0)
                }, "complete")
            else:
                yield format_sse({
                    "type": "error",
                    "message": result.get('message', 'Upload failed')
                }, "error")
                
        except Exception as e:
            app_logger.error(f"Error in streaming upload: {e}", exc_info=True)
            yield format_sse({"type": "error", "message": str(e)}, "error")
    
    return Response(generate_upload_stream(), mimetype="text/event-stream")


@knowledge_api_bp.route("/v1/knowledge/repositories/<int:collection_id>/documents", methods=["POST"])
@require_auth
async def upload_knowledge_document(current_user: dict, collection_id: int):
    """
    Upload a document to a Knowledge repository with SSE progress updates.
    
    Multipart Form Data:
        - file: Document file (PDF, TXT, DOCX, etc.)
        - title: Document title (optional)
        - author: Document author (optional)
        - category: Document category (optional)
        - tags: Comma-separated tags (optional)
        - chunking_strategy: Chunking strategy (fixed_size, paragraph, sentence, semantic)
        - chunk_size: Size of chunks in characters (default: 1000)
        - chunk_overlap: Overlap between chunks (default: 200)
        - embedding_model: Embedding model to use (default: all-MiniLM-L6-v2)
        - stream: Set to 'true' for SSE progress updates (optional)
    """
    # Check if client wants SSE streaming
    form = await request.form
    use_streaming = form.get('stream', '').lower() == 'true'
    
    if use_streaming:
        return await upload_knowledge_document_stream(current_user, collection_id)
    
    # Otherwise use original JSON response
    try:
        # Query collection directly from database
        from trusted_data_agent.core.collection_db import CollectionDatabase
        db = CollectionDatabase()
        conn = db._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT collection_name, repository_type, owner_user_id, chunking_strategy, 
                   chunk_size, chunk_overlap
            FROM collections WHERE id = ?
        """, (collection_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return jsonify({"status": "error", "message": f"Collection {collection_id} not found"}), 404
        
        collection_name = result['collection_name']
        repository_type = result['repository_type']
        owner_user_id = result['owner_user_id']
        
        if repository_type != 'knowledge':
            return jsonify({
                "status": "error",
                "message": f"Collection {collection_id} is not a Knowledge repository"
            }), 400
        
        user_id = current_user.id
        if owner_user_id != user_id:
            return jsonify({"status": "error", "message": "Access denied"}), 403
        
        # Get retriever instance for storage directory
        retriever = get_rag_retriever()
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Get uploaded file
        files = await request.files
        if 'file' not in files:
            return jsonify({"status": "error", "message": "No file provided"}), 400
        
        file = files['file']
        if not file or not file.filename:
            return jsonify({"status": "error", "message": "Invalid file"}), 400
        
        # Get form parameters
        form = await request.form
        title = form.get('title', file.filename)
        author = form.get('author', '')
        category = form.get('category', '')
        tags_str = form.get('tags', '')
        tags = [t.strip() for t in tags_str.split(',') if t.strip()]
        
        chunking_strategy_str = form.get('chunking_strategy', 'semantic')
        chunk_size = int(form.get('chunk_size', 1000))
        chunk_overlap = int(form.get('chunk_overlap', 200))
        embedding_model = form.get('embedding_model', 'all-MiniLM-L6-v2')

        # Save file temporarily (needed by both client-side and server-side paths)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1])
        file_content = file.read()
        temp_file.write(file_content)
        temp_file.flush()
        temp_file.close()

        # Calculate file hash
        content_hash = hashlib.sha256(file_content).hexdigest()

        try:
            # ── Server-side chunking path ──────────────────────────────────────
            # Pass the raw file to the backend SDK — skip text extraction &
            # local chunking entirely.  Follows the Chatbot PDF pattern:
            #   VectorStore.create(document_files=[...], chunk_size=500, ...)
            if chunking_strategy_str == "server_side":
                backend = await retriever._get_knowledge_backend(collection_id)

                if not backend or not backend.has_capability(VectorStoreCapability.SERVER_SIDE_CHUNKING):
                    return jsonify({
                        "status": "error",
                        "message": f"Selected backend does not support server-side chunking. "
                                   f"Use a client-side chunking strategy instead."
                    }), 400

                document_id = str(uuid4())

                await backend.add_document_files(
                    collection_name=collection_name,
                    file_paths=[temp_file.name],
                    chunking_config=ServerSideChunkingConfig(
                        optimized_chunking=form.get("optimized_chunking", "true").lower() == "true",
                        chunk_size=int(form.get("chunk_size", 500)),
                        header_height=float(form.get("header_height", 0.0)),
                        footer_height=float(form.get("footer_height", 0.0)),
                    ),
                )

                app_logger.info(
                    f"Successfully uploaded document '{file.filename}' to Knowledge "
                    f"repository {collection_id} (server-side chunking)"
                )

                # Store document metadata in knowledge_documents table
                from trusted_data_agent.core.collection_db import CollectionDatabase
                db = CollectionDatabase()
                conn = db._get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO knowledge_documents
                    (collection_id, document_id, filename, document_type, title, author,
                     source, category, tags, file_size, content_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    collection_id,
                    document_id,
                    file.filename,
                    os.path.splitext(file.filename)[1].lstrip('.'),
                    title,
                    author,
                    'upload',
                    category,
                    ','.join(tags),
                    len(file_content),
                    content_hash,
                    datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
                conn.close()

                return jsonify({
                    "status": "success",
                    "message": f"Document '{file.filename}' ingested via server-side chunking",
                    "chunks_stored": 0,
                    "metadata": {
                        "document_id": document_id,
                        "filename": file.filename,
                        "document_type": os.path.splitext(file.filename)[1].lstrip('.'),
                        "chunking_mode": "server_side",
                    }
                }), 200

            # ── Client-side chunking path (unchanged) ──────────────────────────
            # Validate chunking strategy enum
            try:
                chunking_strategy = ChunkingStrategy[chunking_strategy_str.upper()]
            except KeyError:
                return jsonify({
                    "status": "error",
                    "message": f"Invalid chunking_strategy: {chunking_strategy_str}"
                }), 400

            # Process document using DocumentUploadHandler
            doc_handler = DocumentUploadHandler()

            # For Knowledge repos, we always extract text
            prepared_doc = doc_handler.prepare_document_for_llm(
                file_path=temp_file.name,
                provider_name="Ollama",  # Force text extraction
                model_name="",
                effective_config={"enabled": True, "use_native_upload": False}
            )

            # Check if content was extracted
            if 'content' not in prepared_doc or not prepared_doc['content']:
                return jsonify({
                    "status": "error",
                    "message": "Failed to extract text from document"
                }), 400

            document_content = prepared_doc['content']

            # Create repository constructor (backend-abstracted path)
            backend = await retriever._get_knowledge_backend(collection_id)
            constructor = create_repository_constructor(
                repository_type=RepositoryType.KNOWLEDGE,
                chroma_client=retriever.client,
                storage_dir=retriever.rag_cases_dir / f"collection_{collection_id}",
                embedding_model=embedding_model,
                chunking_strategy=chunking_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                backend=backend,
            )

            # Construct repository entry
            result = await constructor.construct_async(
                collection_id=collection_id,
                content=document_content,
                collection_name=collection_name,
                filename=file.filename,
                document_type=os.path.splitext(file.filename)[1].lstrip('.'),
                title=title,
                author=author,
                category=category,
                tags=tags,
                source='upload',
                file_size=len(file_content),
                content_hash=content_hash,
                save_original=True
            )

            if result['status'] == 'success':
                app_logger.info(f"Successfully uploaded document '{file.filename}' to Knowledge repository {collection_id}")

                # Store document metadata in database
                from trusted_data_agent.core.collection_db import CollectionDatabase
                db = CollectionDatabase()

                doc_data = {
                    'collection_id': collection_id,
                    'document_id': result['metadata']['document_id'],
                    'filename': file.filename,
                    'document_type': result['metadata']['document_type'],
                    'title': title,
                    'author': author,
                    'source': 'upload',
                    'category': category,
                    'tags': tags,
                    'file_size': len(file_content),
                    'content_hash': content_hash,
                    'created_at': datetime.now(timezone.utc).isoformat()
                }

                # Insert into knowledge_documents table
                conn = db._get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO knowledge_documents
                    (collection_id, document_id, filename, document_type, title, author,
                     source, category, tags, file_size, content_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_data['collection_id'],
                    doc_data['document_id'],
                    doc_data['filename'],
                    doc_data['document_type'],
                    doc_data['title'],
                    doc_data['author'],
                    doc_data['source'],
                    doc_data['category'],
                    ','.join(doc_data['tags']),
                    doc_data['file_size'],
                    doc_data['content_hash'],
                    doc_data['created_at']
                ))
                conn.commit()
                conn.close()

                return jsonify(result), 200
            else:
                return jsonify(result), 400

        finally:
            # Cleanup temp file
            try:
                os.unlink(temp_file.name)
            except:
                pass
    
    except Exception as e:
        app_logger.error(f"Error uploading document to Knowledge repository: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_api_bp.route("/v1/knowledge/repositories/<int:collection_id>/documents", methods=["GET"])
@require_auth
async def list_knowledge_documents(current_user: dict, collection_id: int):
    """
    List all documents in a Knowledge repository.
    
    Returns document metadata (not full content).
    """
    try:
        # Query collection and documents directly from database to avoid APP_STATE sync issues
        from trusted_data_agent.core.collection_db import CollectionDatabase
        db = CollectionDatabase()
        conn = db._get_connection()
        cursor = conn.cursor()
        
        # Verify collection exists and is a Knowledge repository
        cursor.execute("""
            SELECT repository_type, owner_user_id FROM collections
            WHERE id = ?
        """, (collection_id,))
        
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return jsonify({"status": "error", "message": f"Collection {collection_id} not found"}), 404
        
        repository_type = result['repository_type']
        owner_user_id = result['owner_user_id']
        
        if repository_type != 'knowledge':
            conn.close()
            return jsonify({
                "status": "error",
                "message": f"Collection {collection_id} is not a Knowledge repository"
            }), 400
        
        user_id = current_user.id
        if owner_user_id != user_id:
            conn.close()
            return jsonify({"status": "error", "message": "Access denied"}), 403
        
        # Query documents from same connection
        cursor.execute("""
            SELECT * FROM knowledge_documents
            WHERE collection_id = ?
            ORDER BY created_at DESC
        """, (collection_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        documents = []
        for row in rows:
            doc = dict(row)
            # Parse tags
            if doc['tags']:
                doc['tags'] = [t.strip() for t in doc['tags'].split(',')]
            else:
                doc['tags'] = []
            documents.append(doc)
        
        return jsonify({
            "status": "success",
            "collection_id": collection_id,
            "documents": documents,
            "count": len(documents)
        }), 200
    
    except Exception as e:
        app_logger.error(f"Error listing Knowledge documents: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_api_bp.route("/v1/knowledge/repositories/<int:collection_id>/documents/<document_id>", methods=["DELETE"])
@require_auth
async def delete_knowledge_document(current_user: dict, collection_id: int, document_id: str):
    """Delete a document from Knowledge repository."""
    try:
        retriever = get_rag_retriever()
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Query collection directly from database
        from trusted_data_agent.core.collection_db import CollectionDatabase
        db = CollectionDatabase()
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT repository_type, owner_user_id FROM collections
            WHERE id = ?
        """, (collection_id,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return jsonify({"status": "error", "message": f"Collection {collection_id} not found"}), 404
        
        if result['repository_type'] != 'knowledge':
            conn.close()
            return jsonify({"status": "error", "message": "Not a Knowledge repository"}), 400
        
        user_id = current_user.id
        if result['owner_user_id'] != user_id:
            conn.close()
            return jsonify({"status": "error", "message": "Access denied"}), 403
        
        # Delete all chunks for this document via backend
        backend = await retriever._get_knowledge_backend(collection_id)
        if backend:
            from trusted_data_agent.vectorstore import FieldFilter, FilterOp
            coll_meta = retriever.get_collection_metadata(collection_id)
            coll_name = coll_meta["collection_name"] if coll_meta else f"collection_{collection_id}"
            get_result = await backend.get(
                coll_name,
                where=FieldFilter("document_id", FilterOp.EQ, document_id),
                include_documents=False,
                include_metadata=False,
            )
            if get_result.documents:
                chunk_ids = [d.id for d in get_result.documents]
                await backend.delete(coll_name, chunk_ids)
                app_logger.info(f"Deleted {len(chunk_ids)} chunks via backend")
        
        # Delete from database (reuse connection)
        
        cursor.execute("""
            DELETE FROM knowledge_documents
            WHERE collection_id = ? AND document_id = ?
        """, (collection_id, document_id))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted > 0:
            return jsonify({
                "status": "success",
                "message": f"Document {document_id} deleted"
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "Document not found"
            }), 404
    
    except Exception as e:
        app_logger.error(f"Error deleting Knowledge document: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_api_bp.route("/v1/knowledge/repositories/<int:collection_id>/search", methods=["POST"])
@require_auth
async def search_knowledge_repository(current_user: dict, collection_id: int):
    """
    Search within a Knowledge repository.
    
    Body:
        {
            "query": "search text",
            "k": 5,  # number of results
            "filter": {"category": "manual"}  # optional metadata filter
        }
    """
    try:
        retriever = get_rag_retriever()
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Query collection directly from database
        from trusted_data_agent.core.collection_db import CollectionDatabase
        db = CollectionDatabase()
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT repository_type, owner_user_id FROM collections
            WHERE id = ?
        """, (collection_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return jsonify({"status": "error", "message": f"Collection {collection_id} not found"}), 404
        
        if result['repository_type'] != 'knowledge':
            return jsonify({"status": "error", "message": "Not a Knowledge repository"}), 400
        
        user_id = current_user.id
        if result['owner_user_id'] != user_id:
            return jsonify({"status": "error", "message": "Access denied"}), 403
        
        # Get request body
        data = await request.get_json()
        query = data.get('query', '')
        k = data.get('k', 5)
        metadata_filter = data.get('filter', {})
        
        if not query:
            return jsonify({"status": "error", "message": "query is required"}), 400
        
        # Search via backend
        backend = await retriever._get_knowledge_backend(collection_id)
        if not backend:
            return jsonify({"status": "error", "message": "Collection not loaded"}), 404

        coll_meta = retriever.get_collection_metadata(collection_id)
        coll_name = coll_meta["collection_name"] if coll_meta else f"collection_{collection_id}"

        where_filter = None
        if metadata_filter:
            from trusted_data_agent.vectorstore import from_chromadb_where
            where_filter = from_chromadb_where(metadata_filter)

        from trusted_data_agent.vectorstore import get_embedding_provider
        emb_model = coll_meta.get("embedding_model", "all-MiniLM-L6-v2") if coll_meta else "all-MiniLM-L6-v2"
        emb_provider = get_embedding_provider(emb_model)

        query_result = await backend.query(
            coll_name, query_text=query, n_results=k, where=where_filter,
            embedding_provider=emb_provider,
        )

        # Format results
        search_results = []
        for doc, distance in query_result:
            search_results.append({
                'chunk_id': doc.id,
                'content': doc.content,
                'metadata': doc.metadata,
                'distance': distance,
            })
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": search_results,
            "count": len(search_results)
        }), 200
    
    except Exception as e:
        app_logger.error(f"Error searching Knowledge repository: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_api_bp.route("/v1/knowledge/collections/<int:collection_id>/chunks", methods=["GET"])
@require_auth
async def get_knowledge_chunks(current_user: dict, collection_id: int):
    """
    Get all chunks from a Knowledge repository with pagination and search.
    
    Query Parameters:
        - limit: Number of results per page (default: 50)
        - offset: Starting offset for pagination (default: 0)
        - q: Search query text (optional, min 3 characters)
        - light: If 'true', exclude full document text (default: true)
        - sort_by: Field to sort by (default: None)
        - sort_order: 'asc' or 'desc' (default: 'asc')
    
    Returns:
        {
            "chunks": [
                {
                    "id": "chunk_uuid",
                    "document_id": "doc_uuid",
                    "chunk_index": 0,
                    "content": "chunk text content",
                    "token_count": 150,
                    "metadata": {
                        "source_filename": "document.pdf",
                        "page": 1,
                        ...
                    }
                }
            ],
            "total": 1234,
            "collection_id": 5,
            "collection_name": "My Knowledge Base"
        }
    """
    try:
        retriever = get_rag_retriever()
        if not retriever:
            return jsonify({"error": "RAG retriever not initialized"}), 500
        
        # Verify collection exists and user has access
        from trusted_data_agent.core.collection_db import CollectionDatabase
        db = CollectionDatabase()
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, repository_type, owner_user_id FROM collections
            WHERE id = ?
        """, (collection_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return jsonify({"error": f"Collection {collection_id} not found"}), 404
        
        collection_name = result['name']
        repository_type = result['repository_type']
        owner_user_id = result['owner_user_id']
        
        if repository_type != 'knowledge':
            return jsonify({"error": "Not a Knowledge repository"}), 400
        
        user_id = current_user.id
        if owner_user_id != user_id:
            return jsonify({"error": "Access denied"}), 403
        
        # Get pagination parameters
        limit = request.args.get('limit', default=50, type=int)
        offset = request.args.get('offset', default=0, type=int)
        query_text = request.args.get('q', default='', type=str)
        light = request.args.get('light', default='true', type=str).lower() == 'true'
        sort_by = request.args.get('sort_by', default=None, type=str)
        sort_order = request.args.get('sort_order', default='asc', type=str)
        
        # Get backend for this knowledge collection
        backend = await retriever._get_knowledge_backend(collection_id)
        if not backend:
            return jsonify({"error": "Collection not loaded"}), 404

        coll_meta_full = retriever.get_collection_metadata(collection_id)
        coll_name_full = coll_meta_full["collection_name"] if coll_meta_full else f"collection_{collection_id}"

        chunks = []
        total = 0

        # If search query provided (min 3 chars), do semantic search
        if query_text and len(query_text) >= 3:
            try:
                from trusted_data_agent.vectorstore import get_embedding_provider
                emb_model = coll_meta_full.get("embedding_model", "all-MiniLM-L6-v2") if coll_meta_full else "all-MiniLM-L6-v2"
                emb_provider = get_embedding_provider(emb_model)

                query_result = await backend.query(
                    coll_name_full,
                    query_text=query_text,
                    n_results=min(limit, 100),
                    embedding_provider=emb_provider,
                )
                total = len(query_result.documents)
                for doc, distance in query_result:
                    metadata = doc.metadata or {}
                    content = doc.content
                    chunks.append({
                        "id": doc.id,
                        "document_id": metadata.get("document_id", ""),
                        "chunk_index": metadata.get("chunk_index", 0),
                        "content": content if not light else content[:200] + "..." if len(content) > 200 else content,
                        "token_count": metadata.get("token_count", 0),
                        "metadata": metadata,
                        "similarity_score": 1.0 - distance,
                    })
            except Exception as qe:
                app_logger.warning(f"Query failed for knowledge collection '{collection_name}': {qe}")
        else:
            # Get chunks with pagination
            try:
                # Metadata-field sorts require fetching all rows (can't sort JSON in SQL)
                needs_full_fetch = sort_by and sort_by in ['document_id', 'chunk_index', 'token_count']

                if needs_full_fetch:
                    # Full fetch + in-memory sort + slice
                    get_result = await backend.get(coll_name_full)
                    total = get_result.total_count

                    all_chunks = []
                    for doc in get_result.documents:
                        metadata = doc.metadata or {}
                        content = doc.content
                        all_chunks.append({
                            "id": doc.id,
                            "document_id": metadata.get("document_id", ""),
                            "chunk_index": metadata.get("chunk_index", 0),
                            "content": content if not light else content[:200] + "..." if len(content) > 200 else content,
                            "token_count": metadata.get("token_count", 0),
                            "metadata": metadata,
                        })

                    reverse = sort_order.lower() == 'desc'
                    try:
                        all_chunks.sort(key=lambda x: (x.get(sort_by) is None, x.get(sort_by)), reverse=reverse)
                    except Exception as e:
                        app_logger.debug(f"Sorting failed: {e}")

                    chunks = all_chunks[offset:offset + limit]
                else:
                    # Server-side pagination — only fetch the requested page
                    total = await backend.count(coll_name_full)
                    get_result = await backend.get(
                        coll_name_full,
                        offset=offset,
                        limit=limit,
                        include_documents=True,
                        include_metadata=True,
                    )

                    for doc in get_result.documents:
                        metadata = doc.metadata or {}
                        content = doc.content
                        chunks.append({
                            "id": doc.id,
                            "document_id": metadata.get("document_id", ""),
                            "chunk_index": metadata.get("chunk_index", 0),
                            "content": content if not light else content[:200] + "..." if len(content) > 200 else content,
                            "token_count": metadata.get("token_count", 0),
                            "metadata": metadata,
                        })

            except Exception as ge:
                app_logger.error(f"Failed to get chunks for collection '{collection_name}': {ge}", exc_info=True)
        
        return jsonify({
            "chunks": chunks,
            "total": total,
            "query": query_text,
            "collection_id": collection_id,
            "collection_name": collection_name
        }), 200
        
    except Exception as e:
        app_logger.error(f"Error getting knowledge chunks for collection ID {collection_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to get knowledge chunks"}), 500


@knowledge_api_bp.route("/v1/knowledge/collections/<int:collection_id>/chunks/<chunk_id>", methods=["GET"])
@require_auth
async def get_single_chunk(current_user: dict, collection_id: int, chunk_id: str):
    """
    Get a single chunk by ID with full content.
    
    Returns:
        {
            "chunk": {
                "id": "chunk_uuid",
                "document_id": "doc_uuid",
                "chunk_index": 0,
                "content": "full chunk text content",
                "token_count": 150,
                "metadata": {...}
            }
        }
    """
    try:
        retriever = get_rag_retriever()
        if not retriever:
            return jsonify({"error": "RAG retriever not initialized"}), 500
        
        # Verify collection exists and user has access
        from trusted_data_agent.core.collection_db import CollectionDatabase
        db = CollectionDatabase()
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, repository_type, owner_user_id FROM collections
            WHERE id = ?
        """, (collection_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return jsonify({"error": f"Collection {collection_id} not found"}), 404
        
        repository_type = result['repository_type']
        owner_user_id = result['owner_user_id']
        
        if repository_type != 'knowledge':
            return jsonify({"error": "Not a Knowledge repository"}), 400
        
        user_id = current_user.id
        if owner_user_id != user_id:
            return jsonify({"error": "Access denied"}), 403
        
        # Get chunk via backend
        backend = await retriever._get_knowledge_backend(collection_id)
        if not backend:
            return jsonify({"error": "Collection not loaded"}), 404

        coll_meta_chunk = retriever.get_collection_metadata(collection_id)
        coll_name_chunk = coll_meta_chunk["collection_name"] if coll_meta_chunk else f"collection_{collection_id}"

        try:
            get_result = await backend.get(coll_name_chunk, ids=[chunk_id])

            if not get_result.documents:
                return jsonify({"error": "Chunk not found"}), 404

            doc = get_result.documents[0]
            metadata = doc.metadata or {}
            chunk = {
                "id": doc.id,
                "document_id": metadata.get("document_id", ""),
                "chunk_index": metadata.get("chunk_index", 0),
                "content": doc.content,
                "token_count": metadata.get("token_count", 0),
                "metadata": metadata,
            }

            return jsonify({"chunk": chunk}), 200

        except Exception as e:
            app_logger.error(f"Failed to get chunk {chunk_id}: {e}", exc_info=True)
            return jsonify({"error": "Failed to get chunk"}), 500
        
    except Exception as e:
        app_logger.error(f"Error getting chunk {chunk_id} from collection {collection_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to get chunk"}), 500


@knowledge_api_bp.route("/v1/knowledge/test-connection", methods=["POST"])
@require_auth
async def test_knowledge_backend_connection(current_user: dict):
    """Validate Teradata connection credentials without creating a collection.

    Uses VSManager.health() from the teradatagenai SDK to verify connectivity.
    """
    data = await request.get_json()
    backend_type = data.get("backend_type", "chromadb")
    backend_config = data.get("backend_config", {})

    if backend_type == "chromadb":
        return jsonify({"status": "success", "message": "ChromaDB is local — no connection needed"}), 200

    if backend_type != "teradata":
        return jsonify({"status": "error", "message": f"Unknown backend: {backend_type}"}), 400

    # Validate required fields
    has_user_pass = backend_config.get("username") and backend_config.get("password")
    has_pat = backend_config.get("pat_token")
    if not (has_user_pass or has_pat):
        return jsonify({
            "status": "error",
            "message": "Provide either (username + password) or pat_token"
        }), 400
    if not backend_config.get("host"):
        return jsonify({"status": "error", "message": "host is required"}), 400

    try:
        from trusted_data_agent.vectorstore.teradata_backend import TeradataVectorBackend
    except ImportError:
        return jsonify({
            "status": "error",
            "message": "Teradata SDK not installed. Run: pip install teradatagenai teradataml"
        }), 500

    # Use a temporary backend instance with its own dedicated thread so
    # the test-connection does not overwrite the global teradataml context
    # used by active backends (which would cause connection-lost cascades).
    test_backend = TeradataVectorBackend(backend_config)
    try:
        await test_backend.initialize()

        # Health check via the backend's own dedicated thread
        from teradatagenai import VSManager  # type: ignore[import]
        health = await test_backend._run_in_td_thread(VSManager.health)

        return jsonify({
            "status": "success",
            "message": "Connection successful",
            "server_info": {
                "host": backend_config["host"],
                "database": backend_config.get("database"),
                "vs_health": str(health),
            }
        }), 200

    except Exception as e:
        app_logger.warning(f"Teradata test-connection failed: {e}")
        return jsonify({"status": "error", "message": f"Connection failed: {e}"}), 400
    finally:
        await test_backend.shutdown()
