-- Hybrid search configuration per collection.
-- Adds search_mode (semantic/keyword/hybrid) and keyword_weight (0.0-1.0)
-- to enable per-collection hybrid vector search.

ALTER TABLE collections ADD COLUMN search_mode TEXT DEFAULT 'semantic';
ALTER TABLE collections ADD COLUMN hybrid_keyword_weight REAL DEFAULT 0.3;
