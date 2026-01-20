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
            
            # Validate chunking strategy
            try:
                chunking_strategy = ChunkingStrategy[chunking_strategy_str.upper()]
            except KeyError:
                yield format_sse({"type": "error", "message": f"Invalid chunking_strategy: {chunking_strategy_str}"}, "error")
                return
            
            # Save file temporarily
            yield format_sse({"type": "progress", "message": "Saving file...", "percentage": 2}, "progress")
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
            temp_file.write(file_content)
            temp_file.flush()
            temp_file.close()
            
            # Calculate file hash
            content_hash = hashlib.sha256(file_content).hexdigest()
            
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
            
            # Create repository constructor
            constructor = create_repository_constructor(
                repository_type=RepositoryType.KNOWLEDGE,
                chroma_client=retriever.client,
                storage_dir=retriever.rag_cases_dir / f"collection_{collection_id}",
                embedding_model=embedding_model,
                chunking_strategy=chunking_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
            # Construct repository entry with progress updates
            result = constructor.construct(
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
                    progress_msg = await progress_queue.get_nowait()
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
        
        # Validate chunking strategy
        try:
            chunking_strategy = ChunkingStrategy[chunking_strategy_str.upper()]
        except KeyError:
            return jsonify({
                "status": "error",
                "message": f"Invalid chunking_strategy: {chunking_strategy_str}"
            }), 400
        
        # Save file temporarily
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1])
        file_content = file.read()
        temp_file.write(file_content)
        temp_file.flush()
        temp_file.close()
        
        # Calculate file hash
        content_hash = hashlib.sha256(file_content).hexdigest()
        
        try:
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
            
            # Create repository constructor
            constructor = create_repository_constructor(
                repository_type=RepositoryType.KNOWLEDGE,
                chroma_client=retriever.client,
                storage_dir=retriever.rag_cases_dir / f"collection_{collection_id}",
                embedding_model=embedding_model,
                chunking_strategy=chunking_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
            # Construct repository entry
            result = constructor.construct(
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
        
        # Delete from ChromaDB (all chunks for this document)
        collection = retriever.collections.get(collection_id)
        if collection:
            # Get all chunk IDs for this document
            results = collection.get(where={"document_id": document_id})
            if results and results['ids']:
                collection.delete(ids=results['ids'])
                app_logger.info(f"Deleted {len(results['ids'])} chunks from ChromaDB")
        
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
        
        # Search in ChromaDB
        collection = retriever.collections.get(collection_id)
        if not collection:
            return jsonify({"status": "error", "message": "Collection not loaded"}), 404
        
        search_kwargs = {
            'query_texts': [query],
            'n_results': k
        }
        
        if metadata_filter:
            search_kwargs['where'] = metadata_filter
        
        results = collection.query(**search_kwargs)
        
        # Format results
        search_results = []
        if results and results['ids']:
            for i in range(len(results['ids'][0])):
                search_results.append({
                    'chunk_id': results['ids'][0][i],
                    'content': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                    'distance': results['distances'][0][i] if results['distances'] else None
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
        
        # Get ChromaDB collection
        collection = retriever.collections.get(collection_id)
        if not collection:
            return jsonify({"error": "Collection not loaded"}), 404
        
        chunks = []
        total = 0
        
        # If search query provided (min 3 chars), do semantic search
        if query_text and len(query_text) >= 3:
            try:
                results = collection.query(
                    query_texts=[query_text],
                    n_results=min(limit, 100),  # Cap at 100 for performance
                    include=["documents", "metadatas", "distances"]
                )
                
                ids = results.get("ids", [[]])[0]
                documents = results.get("documents", [[]])[0]
                metadatas = results.get("metadatas", [[]])[0]
                distances = results.get("distances", [[]])[0]
                
                total = len(ids)
                
                for i in range(len(ids)):
                    metadata = metadatas[i] or {}
                    chunks.append({
                        "id": ids[i],
                        "document_id": metadata.get("document_id", ""),
                        "chunk_index": metadata.get("chunk_index", 0),
                        "content": documents[i] if not light else documents[i][:200] + "..." if len(documents[i]) > 200 else documents[i],
                        "token_count": metadata.get("token_count", 0),
                        "metadata": metadata,
                        "similarity_score": 1.0 - distances[i] if i < len(distances) else None
                    })
                    
            except Exception as qe:
                app_logger.warning(f"Query failed for knowledge collection '{collection_name}': {qe}")
        else:
            # Get all chunks with pagination
            try:
                all_results = collection.get(
                    include=["documents", "metadatas"],
                    limit=None  # Get all, we'll paginate manually
                )
                
                ids = all_results.get("ids", [])
                documents = all_results.get("documents", [])
                metadatas = all_results.get("metadatas", [])
                
                total = len(ids)
                
                # Build full list first (for sorting)
                all_chunks = []
                for i in range(len(ids)):
                    metadata = metadatas[i] or {}
                    all_chunks.append({
                        "id": ids[i],
                        "document_id": metadata.get("document_id", ""),
                        "chunk_index": metadata.get("chunk_index", 0),
                        "content": documents[i] if not light else documents[i][:200] + "..." if len(documents[i]) > 200 else documents[i],
                        "token_count": metadata.get("token_count", 0),
                        "metadata": metadata
                    })
                
                # Apply sorting if requested
                if sort_by and sort_by in ['id', 'document_id', 'chunk_index', 'token_count']:
                    reverse = sort_order.lower() == 'desc'
                    try:
                        all_chunks.sort(key=lambda x: (x.get(sort_by) is None, x.get(sort_by)), reverse=reverse)
                        app_logger.debug(f"Applied server-side sorting: {sort_by} {sort_order}")
                    except Exception as e:
                        app_logger.debug(f"Sorting failed: {e}")
                
                # Apply pagination
                chunks = all_chunks[offset:offset + limit]
                
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
        
        # Get ChromaDB collection
        collection = retriever.collections.get(collection_id)
        if not collection:
            return jsonify({"error": "Collection not loaded"}), 404
        
        # Get specific chunk by ID
        try:
            result = collection.get(
                ids=[chunk_id],
                include=["documents", "metadatas"]
            )
            
            ids = result.get("ids", [])
            documents = result.get("documents", [])
            metadatas = result.get("metadatas", [])
            
            if not ids or len(ids) == 0:
                return jsonify({"error": "Chunk not found"}), 404
            
            metadata = metadatas[0] or {}
            chunk = {
                "id": ids[0],
                "document_id": metadata.get("document_id", ""),
                "chunk_index": metadata.get("chunk_index", 0),
                "content": documents[0],  # Full content, no truncation
                "token_count": metadata.get("token_count", 0),
                "metadata": metadata
            }
            
            return jsonify({"chunk": chunk}), 200
            
        except Exception as e:
            app_logger.error(f"Failed to get chunk {chunk_id}: {e}", exc_info=True)
            return jsonify({"error": "Failed to get chunk"}), 500
        
    except Exception as e:
        app_logger.error(f"Error getting chunk {chunk_id} from collection {collection_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to get chunk"}), 500
