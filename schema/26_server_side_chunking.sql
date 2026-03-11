-- Migration: Server-side chunking parameters for Teradata EVS collections
-- optimized_chunking: 1 = structure-aware dynamic, 0 = fixed character count
-- ss_chunk_size: characters per chunk (used only when optimized_chunking = 0)
-- header_height / footer_height: points to trim from PDF pages
ALTER TABLE collections ADD COLUMN optimized_chunking INTEGER DEFAULT 1;
ALTER TABLE collections ADD COLUMN ss_chunk_size INTEGER DEFAULT 2000;
ALTER TABLE collections ADD COLUMN header_height INTEGER DEFAULT 0;
ALTER TABLE collections ADD COLUMN footer_height INTEGER DEFAULT 0;
