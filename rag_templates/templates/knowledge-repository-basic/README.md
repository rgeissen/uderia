# Knowledge Repository - Document Storage

A template for creating document-based knowledge repositories with configurable chunking strategies and semantic search capabilities.

## Overview

The Knowledge Repository template enables you to create RAG (Retrieval Augmented Generation) collections from documents without requiring MCP server integration. Upload PDFs, DOCX, TXT, or Markdown files, and the system will automatically chunk, embed, and make them searchable.

## Features

- **Multiple File Format Support**: PDF, DOCX, TXT, Markdown
- **Configurable Chunking Strategies**:
  - **Semantic**: Intelligent boundary detection (currently paragraph-based)
  - **Paragraph**: Split on paragraph boundaries (double newlines)
  - **Sentence**: Group sentences up to chunk size limits
  - **Fixed Size**: Exact character count with configurable overlap
- **Live Preview**: See chunking results before creating the repository
- **Infinite Scroll**: Navigate through large documents efficiently
- **Metadata Tagging**: Organize documents with categories, authors, and tags
- **Flexible Embedding Models**: Choose between speed (MiniLM) or quality (MPNet)

## Configuration Options

### Repository Settings

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repository_name` | string | Yes | Name of the repository (3-100 chars) |
| `description` | string | No | Description of repository purpose |
| `chunking_strategy` | enum | Yes | How documents are split: semantic, paragraph, sentence, fixed_size |
| `chunk_size` | integer | Conditional | Characters per chunk (100-5000, fixed_size only) |
| `chunk_overlap` | integer | Conditional | Overlap between chunks (0-500, fixed_size only) |
| `embedding_model` | enum | Yes | Model for semantic similarity |

### Document Metadata (Optional)

| Field | Description | Example |
|-------|-------------|---------|
| `category` | Document classification | "Technical Documentation" |
| `author` | Document creator | "Engineering Team" |
| `tags` | Comma-separated keywords | "database, performance, sql" |

## Chunking Strategy Guide

### When to use each strategy:

**Semantic / Paragraph**
- ✅ Structured documents (reports, articles, documentation)
- ✅ Natural paragraph breaks
- ✅ Preserving complete thoughts
- ❌ Unformatted text without clear paragraphs

**Sentence**
- ✅ Conversational or prose content
- ✅ Balanced chunk sizes
- ✅ Complete sentences preserved
- ❌ Very short or very long sentences

**Fixed Size**
- ✅ Token-sensitive RAG applications
- ✅ Consistent chunk sizes required
- ✅ Large unstructured documents
- ❌ When semantic meaning must be preserved

## Usage Examples

### 1. Technical Documentation Repository

```json
{
  "repository_name": "API Documentation",
  "description": "REST API reference and integration guides",
  "chunking_strategy": "paragraph",
  "embedding_model": "all-MiniLM-L6-v2"
}
```

**Best for**: Product docs, API references, how-to guides

### 2. Compliance & Policy Repository

```json
{
  "repository_name": "Compliance Policies",
  "description": "Company policies and regulatory requirements",
  "chunking_strategy": "sentence",
  "embedding_model": "all-mpnet-base-v2"
}
```

**Best for**: Legal documents, policies, contracts requiring precise retrieval

### 3. Research Papers Archive

```json
{
  "repository_name": "Research Archive",
  "description": "Academic and industry research papers",
  "chunking_strategy": "fixed_size",
  "chunk_size": 1500,
  "chunk_overlap": 300,
  "embedding_model": "all-mpnet-base-v2"
}
```

**Best for**: Large document corpus, academic papers, long-form content

## Supported File Types

| Format | Extensions | Max Size | Notes |
|--------|-----------|----------|-------|
| PDF | `.pdf` | 50 MB | Text extraction via PyPDF2 |
| Word | `.docx` | 50 MB | Microsoft Word documents |
| Text | `.txt` | 50 MB | Plain text files |
| Markdown | `.md` | 50 MB | Markdown formatted text |

## Embedding Models

### all-MiniLM-L6-v2 (Default)
- **Dimensions**: 384
- **Parameters**: 22M
- **Speed**: Fast
- **Use case**: General purpose, large document sets

### all-mpnet-base-v2
- **Dimensions**: 768
- **Parameters**: 110M
- **Speed**: Moderate
- **Use case**: Higher quality, precision-critical applications

## Workflow

1. **Create Repository**: Configure name, description, chunking strategy, and embedding model
2. **Upload Documents**: Drag & drop or select files (PDF, DOCX, TXT, MD)
3. **Preview Chunks**: See how documents will be chunked before committing
4. **Adjust Settings**: Modify chunking parameters and preview updates automatically
5. **Create**: Repository is created with embedded document chunks
6. **Add More**: Upload additional documents to existing repository at any time

## Live Preview Features

- **Auto-refresh**: Preview updates when files or settings change
- **Initial Display**: Shows first 5 chunks
- **Infinite Scroll**: Load more chunks as you scroll down
- **Chunk Expansion**: Click "Show full chunk" to see complete text
- **Statistics**: Total chunks, character count, truncation notices

## Best Practices

### Chunking Strategy Selection
1. **Start with paragraph** for structured documents
2. **Use sentence** for precise retrieval needs
3. **Use fixed_size** when chunk size consistency is critical
4. **Preview before creating** to validate chunking quality

### Chunk Size Guidelines
- **Small chunks (500-800)**: Precise retrieval, more chunks
- **Medium chunks (1000-1500)**: Balanced (recommended)
- **Large chunks (2000-3000)**: Context-heavy, fewer chunks

### Overlap Recommendations
- **No overlap (0)**: Distinct chunks, no redundancy
- **Small overlap (100-200)**: Recommended for most use cases
- **Large overlap (300-500)**: When context preservation is critical

## API Integration

Knowledge Repositories are created via REST API:

```python
POST /api/v1/rag/collections
{
  "collection_name": "Technical Docs",
  "description": "Product documentation",
  "repository_type": "knowledge",
  "chunking_strategy": "paragraph",
  "chunk_size": 1000,
  "chunk_overlap": 200,
  "embedding_model": "all-MiniLM-L6-v2"
}
```

Document upload:

```python
POST /api/v1/knowledge/repositories/{collection_id}/documents
FormData:
  - file: [document.pdf]
  - category: "Technical"
  - author: "Engineering"
  - tags: "api, rest, documentation"
```

## Limitations

- Maximum file size: 50 MB per document
- PDF preview limited to first 20 pages for performance
- Semantic chunking currently falls back to paragraph strategy
- Embedded documents cannot be modified (delete and re-upload)

## Version History

- **v1.0.0** (2025-11-29): Initial release
  - Support for PDF, DOCX, TXT, MD files
  - Four chunking strategies
  - Live preview with infinite scroll
  - Two embedding model options

## License

AGPL-3.0

## Support

For issues or questions, please visit: https://github.com/rgeissen/uderia
