-- ============================================================
-- Schema: Marketplace Knowledge Graphs
-- Version: 1.0
-- Description: Published knowledge graphs in the intelligence
--              marketplace plus user ratings/reviews.
--              Mirrors marketplace_skills pattern.
-- ============================================================

-- Registry of knowledge graphs published to the marketplace
CREATE TABLE IF NOT EXISTS marketplace_knowledge_graphs (
    id                      VARCHAR(36)  PRIMARY KEY,
    source_profile_id       TEXT         NOT NULL,
    name                    VARCHAR(255) NOT NULL,
    description             TEXT,
    version                 VARCHAR(50),
    author                  VARCHAR(255),
    domain                  VARCHAR(100),                            -- e.g. "finance", "healthcare"
    entity_count            INTEGER      DEFAULT 0,
    relationship_count      INTEGER      DEFAULT 0,
    entity_types_json       TEXT,                                    -- JSON object: {"table": 5, "column": 20, ...}
    relationship_types_json TEXT,                                    -- JSON object: {"contains": 10, "foreign_key": 5, ...}
    tags_json               TEXT,                                    -- JSON array of tags
    publisher_user_id       VARCHAR(36)  NOT NULL,
    visibility              VARCHAR(20)  DEFAULT 'public',           -- 'public' or 'targeted'
    manifest_json           TEXT,                                    -- Full export metadata for preview
    content_hash            VARCHAR(64),                             -- SHA256 of exported JSON for dedup
    download_count          INTEGER      DEFAULT 0,
    install_count           INTEGER      DEFAULT 0,
    published_at            DATETIME     NOT NULL,
    updated_at              DATETIME     NOT NULL,
    FOREIGN KEY (publisher_user_id) REFERENCES users(id)
);

-- User ratings/reviews for published knowledge graphs
CREATE TABLE IF NOT EXISTS knowledge_graph_ratings (
    id                  VARCHAR(36) PRIMARY KEY,
    kg_marketplace_id   VARCHAR(36) NOT NULL,
    user_id             VARCHAR(36) NOT NULL,
    rating              INTEGER     NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment             TEXT,
    created_at          DATETIME    NOT NULL,
    updated_at          DATETIME    NOT NULL,
    FOREIGN KEY (kg_marketplace_id) REFERENCES marketplace_knowledge_graphs(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Knowledge graph marketplace governance settings
CREATE TABLE IF NOT EXISTS kg_marketplace_settings (
    id            INTEGER PRIMARY KEY,
    setting_key   TEXT NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO kg_marketplace_settings (setting_key, setting_value) VALUES
    ('kg_marketplace_enabled', 'true');

-- Indexes
CREATE INDEX IF NOT EXISTS idx_marketplace_kg_publisher
    ON marketplace_knowledge_graphs(publisher_user_id);

CREATE INDEX IF NOT EXISTS idx_marketplace_kg_visibility
    ON marketplace_knowledge_graphs(visibility);

CREATE INDEX IF NOT EXISTS idx_marketplace_kg_domain
    ON marketplace_knowledge_graphs(domain);

CREATE INDEX IF NOT EXISTS idx_marketplace_kg_published_at
    ON marketplace_knowledge_graphs(published_at);

CREATE INDEX IF NOT EXISTS idx_kg_ratings_kg
    ON knowledge_graph_ratings(kg_marketplace_id);

CREATE INDEX IF NOT EXISTS idx_kg_ratings_user
    ON knowledge_graph_ratings(user_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_ratings_unique
    ON knowledge_graph_ratings(kg_marketplace_id, user_id);
