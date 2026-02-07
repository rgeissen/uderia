"""
Abstract Repository Constructor Framework

Provides a unified, polymorphic approach to building both Planner and Knowledge repositories.
This framework harmonizes document processing, embedding generation, and storage patterns
across different repository types.

Repository Types:
- Planner Repositories: Store execution patterns and strategies
- Knowledge Repositories: Store reference documents and domain knowledge

Key Abstractions:
- RepositoryConstructor: Base class defining common construction pipeline
- DocumentProcessor: Handles chunking, parsing, metadata extraction
- EmbeddingStrategy: Configurable embedding generation
- StorageAdapter: Manages persistence to ChromaDB and file system
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
import hashlib
import uuid

from chromadb.utils import embedding_functions

logger = logging.getLogger("repository_constructor")


class RepositoryType(Enum):
    """Types of repositories supported by the system."""
    PLANNER = "planner"  # Execution patterns and strategies
    KNOWLEDGE = "knowledge"  # Reference documents and domain knowledge


class ChunkingStrategy(Enum):
    """Document chunking strategies for Knowledge repositories."""
    FIXED_SIZE = "fixed_size"  # Fixed character/token count
    SEMANTIC = "semantic"  # Semantic boundary detection
    PARAGRAPH = "paragraph"  # Paragraph-based
    SENTENCE = "sentence"  # Sentence-based
    NONE = "none"  # No chunking (for Planner repos)


class DocumentChunk:
    """Represents a chunk of a document with metadata."""
    
    def __init__(self, content: str, metadata: Dict[str, Any], chunk_index: int = 0):
        self.content = content
        self.metadata = metadata
        self.chunk_index = chunk_index
        self.chunk_id = self._generate_chunk_id()
    
    def _generate_chunk_id(self) -> str:
        """Generate a unique ID for this chunk."""
        content_hash = hashlib.sha256(self.content.encode()).hexdigest()[:16]
        doc_id = self.metadata.get('document_id', 'unknown')
        return f"{doc_id}_chunk_{self.chunk_index}_{content_hash}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'chunk_id': self.chunk_id,
            'content': self.content,
            'metadata': self.metadata,
            'chunk_index': self.chunk_index
        }


class DocumentProcessor:
    """Handles document processing with configurable chunking strategies."""
    
    def __init__(self, chunking_strategy: ChunkingStrategy = ChunkingStrategy.SEMANTIC,
                 chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunking_strategy = chunking_strategy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def process_document(self, content: str, metadata: Dict[str, Any]) -> List[DocumentChunk]:
        """
        Process a document into chunks based on the configured strategy.
        
        Args:
            content: Document text content
            metadata: Document metadata (filename, source, etc.)
            
        Returns:
            List of DocumentChunk objects
        """
        if self.chunking_strategy == ChunkingStrategy.NONE:
            # No chunking - return single chunk (for Planner repos)
            return [DocumentChunk(content, metadata, 0)]
        
        elif self.chunking_strategy == ChunkingStrategy.FIXED_SIZE:
            return self._chunk_fixed_size(content, metadata)
        
        elif self.chunking_strategy == ChunkingStrategy.PARAGRAPH:
            return self._chunk_by_paragraph(content, metadata)
        
        elif self.chunking_strategy == ChunkingStrategy.SENTENCE:
            return self._chunk_by_sentence(content, metadata)
        
        elif self.chunking_strategy == ChunkingStrategy.SEMANTIC:
            # For now, fall back to paragraph chunking
            # TODO: Implement semantic boundary detection
            return self._chunk_by_paragraph(content, metadata)
        
        else:
            raise ValueError(f"Unsupported chunking strategy: {self.chunking_strategy}")
    
    def _chunk_fixed_size(self, content: str, metadata: Dict[str, Any]) -> List[DocumentChunk]:
        """Chunk document into fixed-size pieces with overlap."""
        chunks = []
        start = 0
        chunk_index = 0
        
        while start < len(content):
            end = start + self.chunk_size
            chunk_text = content[start:end]
            
            chunk_metadata = metadata.copy()
            chunk_metadata['chunk_method'] = 'fixed_size'
            chunk_metadata['chunk_size'] = len(chunk_text)
            
            chunks.append(DocumentChunk(chunk_text, chunk_metadata, chunk_index))
            
            start += self.chunk_size - self.chunk_overlap
            chunk_index += 1
        
        return chunks
    
    def _chunk_by_paragraph(self, content: str, metadata: Dict[str, Any]) -> List[DocumentChunk]:
        """
        Chunk document by paragraphs with intelligent size management.
        
        Strategy:
        1. Split on paragraph boundaries (double newlines)
        2. Combine small paragraphs up to chunk_size
        3. Split large paragraphs that exceed chunk_size * 1.5
        4. Respect natural document structure while maintaining reasonable chunk sizes
        """
        # Split on double newlines to respect paragraph boundaries
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        # If we got very few paragraphs and they're huge, fall back to fixed-size
        if len(paragraphs) <= 3 and sum(len(p) for p in paragraphs) > self.chunk_size * 10:
            metadata_copy = metadata.copy()
            metadata_copy['fallback_reason'] = 'few_large_paragraphs'
            logger.warning(f"Document has only {len(paragraphs)} paragraph(s) with total length "
                         f"{sum(len(p) for p in paragraphs)} chars. Falling back to fixed-size chunking.")
            return self._chunk_fixed_size(content, metadata_copy)
        
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_index = 0
        max_chunk_size = int(self.chunk_size * 1.5)  # Allow 50% flexibility
        
        for para in paragraphs:
            para_size = len(para)
            
            # If this paragraph alone exceeds max size, split it
            if para_size > max_chunk_size:
                # First, flush any accumulated paragraphs
                if current_chunk:
                    chunk_text = '\n\n'.join(current_chunk)
                    chunk_metadata = metadata.copy()
                    chunk_metadata['chunk_method'] = 'paragraph'
                    chunk_metadata['paragraph_count'] = len(current_chunk)
                    chunks.append(DocumentChunk(chunk_text, chunk_metadata, chunk_index))
                    current_chunk = []
                    current_size = 0
                    chunk_index += 1
                
                # Split large paragraph using fixed-size chunking
                para_chunks = self._split_large_paragraph(para, metadata, chunk_index)
                chunks.extend(para_chunks)
                chunk_index += len(para_chunks)
                continue
            
            # If adding this paragraph exceeds chunk_size, create new chunk
            if current_size + para_size > self.chunk_size and current_chunk:
                chunk_text = '\n\n'.join(current_chunk)
                chunk_metadata = metadata.copy()
                chunk_metadata['chunk_method'] = 'paragraph'
                chunk_metadata['paragraph_count'] = len(current_chunk)
                chunks.append(DocumentChunk(chunk_text, chunk_metadata, chunk_index))
                current_chunk = []
                current_size = 0
                chunk_index += 1
            
            # Add paragraph to current chunk
            current_chunk.append(para)
            current_size += para_size
        
        # Add remaining paragraphs as final chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunk_metadata = metadata.copy()
            chunk_metadata['chunk_method'] = 'paragraph'
            chunk_metadata['paragraph_count'] = len(current_chunk)
            chunks.append(DocumentChunk(chunk_text, chunk_metadata, chunk_index))
        
        return chunks
    
    def _split_large_paragraph(self, paragraph: str, metadata: Dict[str, Any], 
                              start_index: int) -> List[DocumentChunk]:
        """
        Split a large paragraph that exceeds chunk_size using sentence boundaries.
        Falls back to fixed-size if no sentence boundaries found.
        """
        import re
        
        # Try to split on sentences first
        sentences = re.split(r'(?<=[.!?])\s+', paragraph)
        
        if len(sentences) <= 1:
            # No sentence boundaries, use fixed-size splitting
            chunks = []
            start = 0
            local_index = 0
            
            while start < len(paragraph):
                end = start + self.chunk_size
                chunk_text = paragraph[start:end]
                
                chunk_metadata = metadata.copy()
                chunk_metadata['chunk_method'] = 'paragraph_split_fixed'
                chunk_metadata['split_reason'] = 'no_sentence_boundaries'
                
                chunks.append(DocumentChunk(chunk_text, chunk_metadata, start_index + local_index))
                start += self.chunk_size - self.chunk_overlap
                local_index += 1
            
            return chunks
        
        # Split by sentences respecting chunk_size
        chunks = []
        current_chunk = []
        current_size = 0
        local_index = 0
        
        for sentence in sentences:
            sentence_size = len(sentence)
            
            if current_size + sentence_size > self.chunk_size and current_chunk:
                chunk_text = ' '.join(current_chunk)
                chunk_metadata = metadata.copy()
                chunk_metadata['chunk_method'] = 'paragraph_split_sentence'
                chunk_metadata['sentence_count'] = len(current_chunk)
                
                chunks.append(DocumentChunk(chunk_text, chunk_metadata, start_index + local_index))
                current_chunk = []
                current_size = 0
                local_index += 1
            
            current_chunk.append(sentence)
            current_size += sentence_size
        
        # Add remaining sentences
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            chunk_metadata = metadata.copy()
            chunk_metadata['chunk_method'] = 'paragraph_split_sentence'
            chunk_metadata['sentence_count'] = len(current_chunk)
            
            chunks.append(DocumentChunk(chunk_text, chunk_metadata, start_index + local_index))
        
        return chunks
    
    def _chunk_by_sentence(self, content: str, metadata: Dict[str, Any]) -> List[DocumentChunk]:
        """Chunk document by sentences."""
        # Simple sentence splitting (can be enhanced with NLP libraries)
        import re
        sentences = re.split(r'(?<=[.!?])\s+', content)
        chunks = []
        
        current_chunk = []
        current_size = 0
        chunk_index = 0
        
        for sentence in sentences:
            sentence_size = len(sentence)
            
            if current_size + sentence_size > self.chunk_size and current_chunk:
                # Create chunk from accumulated sentences
                chunk_text = ' '.join(current_chunk)
                chunk_metadata = metadata.copy()
                chunk_metadata['chunk_method'] = 'sentence'
                chunk_metadata['sentence_count'] = len(current_chunk)
                
                chunks.append(DocumentChunk(chunk_text, chunk_metadata, chunk_index))
                
                current_chunk = []
                current_size = 0
                chunk_index += 1
            
            current_chunk.append(sentence)
            current_size += sentence_size
        
        # Add remaining sentences
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            chunk_metadata = metadata.copy()
            chunk_metadata['chunk_method'] = 'sentence'
            chunk_metadata['sentence_count'] = len(current_chunk)
            
            chunks.append(DocumentChunk(chunk_text, chunk_metadata, chunk_index))
        
        return chunks


class EmbeddingStrategy:
    """Handles embedding generation with configurable models."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name
        )
        logger.info(f"Initialized embedding strategy with model: {model_name}")
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        return self.embedding_function(texts)


class StorageAdapter:
    """Manages persistence to ChromaDB and file system."""
    
    def __init__(self, chroma_client, storage_dir: Path):
        self.chroma_client = chroma_client
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def store_chunks(self, collection, chunks: List[DocumentChunk],
                    embedding_function, progress_callback=None) -> Dict[str, Any]:
        """
        Store document chunks in ChromaDB and optionally on file system.
        
        Args:
            progress_callback: Optional async function to report progress
        
        Returns:
            Dictionary with storage results
        """
        if not chunks:
            return {"status": "error", "message": "No chunks to store"}
        
        total_chunks = len(chunks)
        
        # Prepare data for ChromaDB in batches to allow progress updates
        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        
        # Add chunk_index and token count to metadata
        metadatas = []
        for i, chunk in enumerate(chunks):
            metadata = chunk.metadata.copy()
            metadata['chunk_index'] = chunk.chunk_index
            # Calculate approximate token count (rough estimate: ~4 chars per token)
            metadata['token_count'] = len(chunk.content) // 4
            metadatas.append(metadata)
            
            # Report progress during metadata preparation
            if progress_callback and i % 10 == 0:
                import asyncio
                asyncio.create_task(progress_callback(
                    f"Preparing chunk {i+1}/{total_chunks} for embedding",
                    int((i / total_chunks) * 30)  # 0-30% for prep
                ))
        
        # Report embedding start
        if progress_callback:
            import asyncio
            asyncio.create_task(progress_callback(
                f"Generating embeddings for {total_chunks} chunks...",
                30
            ))
        
        # Store in ChromaDB (this triggers embedding generation)
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        
        logger.info(f"Stored {len(chunks)} chunks in ChromaDB collection: {collection.name}")
        
        return {
            "status": "success",
            "chunks_stored": len(chunks),
            "collection_name": collection.name
        }
    
    def save_document_file(self, document_id: str, content: str, metadata: Dict[str, Any]) -> Path:
        """Save original document to file system for reference."""
        doc_file = self.storage_dir / f"doc_{document_id}.json"
        
        doc_data = {
            "document_id": document_id,
            "content": content,
            "metadata": metadata,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        with open(doc_file, 'w', encoding='utf-8') as f:
            json.dump(doc_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved document file: {doc_file}")
        return doc_file


class RepositoryConstructor(ABC):
    """
    Abstract base class for repository constructors.
    
    Defines the common pipeline for building repositories regardless of type.
    Subclasses implement type-specific behavior while reusing shared infrastructure.
    """
    
    def __init__(self, repository_type: RepositoryType, chroma_client, storage_dir: Path,
                 embedding_model: str = "all-MiniLM-L6-v2"):
        self.repository_type = repository_type
        self.chroma_client = chroma_client
        self.storage_dir = Path(storage_dir)
        self.embedding_strategy = EmbeddingStrategy(embedding_model)
        self.storage_adapter = StorageAdapter(chroma_client, storage_dir)
        
        # Configure document processor based on repository type
        if repository_type == RepositoryType.PLANNER:
            # Planner repos don't chunk - store complete execution traces
            self.document_processor = DocumentProcessor(ChunkingStrategy.NONE)
        else:
            # Knowledge repos use semantic chunking
            self.document_processor = DocumentProcessor(ChunkingStrategy.SEMANTIC)
    
    @abstractmethod
    def prepare_metadata(self, **kwargs) -> Dict[str, Any]:
        """Prepare repository-specific metadata. Implemented by subclasses."""
        pass
    
    @abstractmethod
    def validate_input(self, **kwargs) -> Tuple[bool, Optional[str]]:
        """Validate input data. Returns (is_valid, error_message)."""
        pass
    
    def construct(self, collection_id: int, content: str, **kwargs) -> Dict[str, Any]:
        """
        Main construction pipeline - processes and stores content in repository.
        
        Args:
            collection_id: Target collection ID
            content: Text content to process
            **kwargs: Additional metadata and configuration (including optional progress_callback)
            
        Returns:
            Dictionary with construction results
        """
        progress_callback = kwargs.get('progress_callback')
        
        # Step 1: Validate input
        if progress_callback:
            import asyncio
            asyncio.create_task(progress_callback("Validating document...", 5))
        
        is_valid, error_msg = self.validate_input(content=content, **kwargs)
        if not is_valid:
            return {"status": "error", "message": error_msg}
        
        # Step 2: Prepare metadata
        if progress_callback:
            import asyncio
            asyncio.create_task(progress_callback("Preparing metadata...", 10))
        
        metadata = self.prepare_metadata(
            collection_id=collection_id,
            repository_type=self.repository_type.value,
            **kwargs
        )
        
        # Step 3: Process document into chunks
        if progress_callback:
            import asyncio
            asyncio.create_task(progress_callback("Chunking document...", 15))
        
        chunks = self.document_processor.process_document(content, metadata)
        logger.info(f"Processed document into {len(chunks)} chunk(s)")
        
        if progress_callback:
            import asyncio
            asyncio.create_task(progress_callback(f"Created {len(chunks)} chunks", 20))
        
        # Step 4: Get or create collection
        collection_name = kwargs.get('collection_name', f"collection_{collection_id}")
        collection = self.chroma_client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_strategy.embedding_function,
            metadata={"repository_type": self.repository_type.value}
        )
        
        # Step 5: Store chunks (this is the slow part - embeddings)
        result = self.storage_adapter.store_chunks(
            collection, chunks, self.embedding_strategy.embedding_function,
            progress_callback=progress_callback
        )
        
        if progress_callback:
            import asyncio
            asyncio.create_task(progress_callback("Embeddings complete, saving document...", 90))
        
        # Step 6: Save original document if requested
        if kwargs.get('save_original', True):
            document_id = metadata.get('document_id', str(uuid.uuid4()))
            self.storage_adapter.save_document_file(document_id, content, metadata)
        
        if progress_callback:
            import asyncio
            asyncio.create_task(progress_callback("Document upload complete!", 100))
        
        result.update({
            "repository_type": self.repository_type.value,
            "collection_id": collection_id,
            "metadata": metadata
        })
        
        return result


class PlannerRepositoryConstructor(RepositoryConstructor):
    """Constructor for Planner Repositories - stores execution patterns."""
    
    def __init__(self, chroma_client, storage_dir: Path, embedding_model: str = "all-MiniLM-L6-v2"):
        super().__init__(RepositoryType.PLANNER, chroma_client, storage_dir, embedding_model)
    
    def prepare_metadata(self, **kwargs) -> Dict[str, Any]:
        """Prepare metadata for planner execution pattern."""
        return {
            "document_id": kwargs.get('case_id', str(uuid.uuid4())),
            "collection_id": kwargs['collection_id'],
            "repository_type": "planner",
            "user_query": kwargs.get('user_query', ''),
            "strategy_type": kwargs.get('strategy_type', 'unknown'),
            "mcp_server_id": kwargs.get('mcp_server_id'),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "is_most_efficient": kwargs.get('is_most_efficient', False),
            "output_tokens": kwargs.get('output_tokens', 0),
            "user_feedback_score": kwargs.get('user_feedback_score')
        }
    
    def validate_input(self, **kwargs) -> Tuple[bool, Optional[str]]:
        """Validate planner repository input."""
        content = kwargs.get('content', '')
        if not content or len(content) < 10:
            return False, "Content is required and must be at least 10 characters"
        
        if not kwargs.get('user_query'):
            return False, "user_query is required for planner repositories"
        
        return True, None


class KnowledgeRepositoryConstructor(RepositoryConstructor):
    """Constructor for Knowledge Repositories - stores reference documents."""
    
    def __init__(self, chroma_client, storage_dir: Path, embedding_model: str = "all-MiniLM-L6-v2",
                 chunking_strategy: ChunkingStrategy = ChunkingStrategy.SEMANTIC,
                 chunk_size: int = 1000, chunk_overlap: int = 200):
        super().__init__(RepositoryType.KNOWLEDGE, chroma_client, storage_dir, embedding_model)
        
        # Override document processor with Knowledge-specific configuration
        self.document_processor = DocumentProcessor(chunking_strategy, chunk_size, chunk_overlap)
    
    def prepare_metadata(self, **kwargs) -> Dict[str, Any]:
        """Prepare metadata for knowledge document."""
        # Convert tags list to comma-separated string for ChromaDB
        tags = kwargs.get('tags', [])
        tags_str = ','.join(tags) if isinstance(tags, list) else str(tags)
        
        return {
            "document_id": kwargs.get('document_id', str(uuid.uuid4())),
            "collection_id": kwargs['collection_id'],
            "repository_type": "knowledge",
            "filename": kwargs.get('filename', 'unknown'),
            "document_type": kwargs.get('document_type', 'text'),
            "source": kwargs.get('source', 'upload'),
            "title": kwargs.get('title', ''),
            "author": kwargs.get('author', ''),
            "tags": tags_str,
            "category": kwargs.get('category', ''),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "file_size": kwargs.get('file_size', 0),
            "page_count": kwargs.get('page_count', 0)
        }
    
    def validate_input(self, **kwargs) -> Tuple[bool, Optional[str]]:
        """Validate knowledge repository input."""
        content = kwargs.get('content', '')
        if not content or len(content) < 50:
            return False, "Content is required and must be at least 50 characters"
        
        filename = kwargs.get('filename', '')
        if not filename:
            return False, "filename is required for knowledge repositories"
        
        return True, None


# Factory function for creating appropriate constructor
def create_repository_constructor(repository_type: RepositoryType, chroma_client,
                                  storage_dir: Path, **config) -> RepositoryConstructor:
    """
    Factory function to create appropriate constructor based on repository type.
    
    Args:
        repository_type: Type of repository to construct
        chroma_client: ChromaDB client instance
        storage_dir: Directory for file storage
        **config: Additional configuration options
        
    Returns:
        Appropriate RepositoryConstructor instance
    """
    if repository_type == RepositoryType.PLANNER:
        return PlannerRepositoryConstructor(
            chroma_client, storage_dir,
            embedding_model=config.get('embedding_model', 'all-MiniLM-L6-v2')
        )
    elif repository_type == RepositoryType.KNOWLEDGE:
        return KnowledgeRepositoryConstructor(
            chroma_client, storage_dir,
            embedding_model=config.get('embedding_model', 'all-MiniLM-L6-v2'),
            chunking_strategy=config.get('chunking_strategy', ChunkingStrategy.SEMANTIC),
            chunk_size=config.get('chunk_size', 1000),
            chunk_overlap=config.get('chunk_overlap', 200)
        )
    else:
        raise ValueError(f"Unsupported repository type: {repository_type}")
