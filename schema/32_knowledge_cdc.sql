-- Migration: Knowledge Repository Change Data Management (CDC)
--
-- Adds per-document fields needed for:
--   • Source URI tracking (where the document came from)
--   • Ingest epoch (Unix timestamp of last successful write; enables generation-based chunk cleanup)
--   • Auto-sync opt-in (scheduler re-fetches source_uri and re-embeds on change)
--   • Last-checked timestamp (staleness detection in UI)
--
-- Collection-level fields:
--   • sync_interval  — how often the scheduler should check sync-enabled documents
--   • embedding_model_locked — 1 after a validated re-index; 0 means model consistency unverified

-- knowledge_documents CDC fields
ALTER TABLE knowledge_documents ADD COLUMN source_uri TEXT;
ALTER TABLE knowledge_documents ADD COLUMN ingest_epoch INTEGER;
ALTER TABLE knowledge_documents ADD COLUMN sync_enabled INTEGER DEFAULT 0;
ALTER TABLE knowledge_documents ADD COLUMN last_checked_at TEXT;
ALTER TABLE knowledge_documents ADD COLUMN chunk_count INTEGER DEFAULT 0;

-- collections CDC fields
ALTER TABLE collections ADD COLUMN sync_interval TEXT DEFAULT 'daily';
ALTER TABLE collections ADD COLUMN embedding_model_locked INTEGER DEFAULT 0;

-- Backfill ingest_epoch for existing rows using created_at
UPDATE knowledge_documents
SET ingest_epoch = CAST(strftime('%s', created_at) AS INTEGER)
WHERE ingest_epoch IS NULL AND created_at IS NOT NULL;

-- Scheduler staleness sweep index
CREATE INDEX IF NOT EXISTS idx_knowledge_docs_sync
    ON knowledge_documents (collection_id, sync_enabled, last_checked_at);

-- Upsert lookup index (get_document_by_filename)
CREATE INDEX IF NOT EXISTS idx_knowledge_docs_filename
    ON knowledge_documents (collection_id, filename);
