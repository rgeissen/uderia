# Document Upload Integration - SQL Query Template (Document Context)

## Overview

This template integrates the **DocumentUploadHandler** abstraction layer to provide provider-aware document handling for technical documentation used as context in SQL query generation.

## Key Features

### 1. Provider-Aware Document Handling
- **Native Upload**: For providers that support it (Google, Anthropic, Amazon)
- **Text Extraction Fallback**: Automatic fallback for providers without native support
- **Configuration-Driven**: Uses database-backed configuration managed via admin UI

### 2. Flexible Input Options
Users can provide context documentation via:
- **File Upload** (`document_file`): Uploads actual files (.pdf, .doc, .docx, .txt)
- **Text Content** (`document_content`): Direct text input
- **Either/Or**: At least one must be provided

### 3. Admin Control
Administrators can configure document upload behavior per provider:
- Enable/disable document upload capability
- Force text extraction (disable native upload)
- Override file size limits
- Override supported formats
- Add operational notes

## Template Structure

### Input Variables

```json
{
  "document_file": {
    "type": "file",
    "required": false,
    "description": "Upload technical documentation file",
    "validation": {
      "allowed_extensions": [".pdf", ".doc", ".docx", ".txt"],
      "max_size_mb": 32
    },
    "upload_config": {
      "use_abstraction": true,
      "provider_aware": true,
      "fallback_to_extraction": true
    }
  },
  "document_content": {
    "type": "text",
    "required": false,
    "description": "Alternative to file upload"
  }
}
```

### Validation Rules

```json
{
  "document_content_or_file": {
    "at_least_one": ["document_file", "document_content"]
  },
  "document_processing": {
    "use_upload_handler": true,
    "handler_class": "DocumentUploadHandler",
    "handler_method": "prepare_document_for_llm",
    "auto_extract_text": true,
    "respect_provider_config": true
  }
}
```

## Processing Workflow

### Step-by-Step Flow

1. **Input Validation**
   - Check that either `document_file` or `document_content` is provided
   - Validate file format and size if file provided

2. **Document Processing** (if `document_file` provided)
   ```python
   from trusted_data_agent.llm.document_upload import DocumentUploadHandler
   
   handler = DocumentUploadHandler()
   result = handler.prepare_document_for_llm(
       file_path=document_file_path,
       provider_name=current_provider,
       model_name=current_model,
       effective_config=config_from_database
   )
   ```

3. **Configuration Lookup**
   - Query `document_upload_configurations` table for provider config
   - Respect admin settings (enabled, use_native_upload, overrides)

4. **Method Selection**
   - **Native Upload**: If enabled and provider supports it
   - **Text Extraction**: If native disabled or not supported
   - Result includes method used and extracted/prepared content

5. **Context Integration**
   - Extracted/prepared content becomes part of Phase 1 context
   - Used in SQL query generation with technical documentation context

## Provider Capabilities

| Provider | Capability | Native Formats | Max Size | Config Table |
|----------|-----------|----------------|----------|--------------|
| Google | NATIVE_FULL | PDF, images | 20 MB | ✅ Admin UI |
| Anthropic | NATIVE_FULL | PDF, images | 32 MB | ✅ Admin UI |
| Amazon | NATIVE_FULL | PDF, images | 25 MB | ✅ Admin UI |
| OpenAI | NATIVE_VISION | Images only | 20 MB | ✅ Admin UI |
| Azure | NATIVE_VISION | Images only | 20 MB | ✅ Admin UI |
| Friendli | TEXT_EXTRACTION | N/A | N/A | ✅ Admin UI |
| Ollama | TEXT_EXTRACTION | N/A | N/A | ✅ Admin UI |

## Usage Examples

### Example 1: File Upload with Native Support
```json
{
  "user_query": "Show me all tables with high fragmentation",
  "sql_statement": "SELECT DatabaseName, TableName, CurrentPerm, PeakPerm FROM DBC.TableSize WHERE (CurrentPerm - PeakPerm) / NULLIFZERO(PeakPerm) > 0.20",
  "context_topic": "performance tuning",
  "database_name": "production",
  "document_file": "dba_performance_guide.pdf"
}
```
**Result**: 
- Google/Anthropic/Amazon: Native PDF upload
- Others: Automatic text extraction

### Example 2: Direct Text Content
```json
{
  "user_query": "Show me all tables with high fragmentation",
  "sql_statement": "SELECT DatabaseName, TableName, CurrentPerm, PeakPerm FROM DBC.TableSize WHERE (CurrentPerm - PeakPerm) / NULLIFZERO(PeakPerm) > 0.20",
  "context_topic": "performance tuning",
  "database_name": "production",
  "document_content": "[Excerpt from DBA Performance Guide] Table fragmentation occurs when..."
}
```
**Result**: Direct text usage, bypasses document upload handler

### Example 3: Admin Forces Text Extraction
Admin Configuration:
```
Provider: Google
Enabled: Yes
Use Native Upload: No (force text extraction)
```

Request with `document_file`:
**Result**: Text extraction used even though Google supports native upload

## Admin Configuration

### Access
Navigate to: **Admin → Application Configuration → Document Upload Configuration**

### Settings Per Provider

1. **Enabled**: Enable/disable document upload for this provider
2. **Use Native Upload**: Toggle between native upload and text extraction
3. **Max File Size Override**: Custom file size limit (overrides default)
4. **Supported Formats Override**: Custom format list
5. **Admin Notes**: Operational notes for team reference

### Database Schema

```sql
CREATE TABLE document_upload_configurations (
    provider TEXT PRIMARY KEY,
    enabled BOOLEAN DEFAULT true,
    use_native_upload BOOLEAN DEFAULT true,
    max_file_size_mb_override INTEGER,
    supported_formats_override TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Implementation Notes

### Template Processing
When RAG template manager processes this template:

1. Checks `validation_rules.document_processing.use_upload_handler`
2. If `document_file` provided, calls `DocumentUploadHandler.prepare_document_for_llm()`
3. Handler returns:
   ```python
   {
       'method': 'native_google' | 'native_anthropic' | 'text_extraction',
       'content': 'extracted or prepared text',
       'content_type': 'application/pdf',
       'file_size': 1234567,
       'filename': 'guide.pdf'
   }
   ```
4. Content used as context in Phase 1 SQL generation

### Error Handling
- Invalid file format → Validation error before processing
- File too large → Validation error based on config
- Extraction failure → Falls back to error message in content
- Provider config missing → Uses default settings

## Version History

- **v1.1.0** (2025-11-27): Added DocumentUploadHandler integration
- **v1.0.0** (2025-11-21): Initial template with hardcoded text content

## Related Documentation

- `src/trusted_data_agent/llm/document_upload.py` - Handler implementation
- `src/trusted_data_agent/llm/document_upload_config_manager.py` - Config management
- `src/trusted_data_agent/auth/database.py` - Database schema (init_document_upload_configurations)
- `static/js/handlers/documentUploadConfigManager.js` - Admin UI
