-- ============================================================
-- Schema: Marketplace Agent Packs
-- Version: 1.0
-- Description: Published agent packs in the intelligence
--              marketplace plus user ratings/reviews.
-- ============================================================

-- Registry of agent packs published to the marketplace
CREATE TABLE IF NOT EXISTS marketplace_agent_packs (
    id            VARCHAR(36)  PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    description   TEXT,
    version       VARCHAR(50),
    author        VARCHAR(255),
    pack_type     VARCHAR(20)  NOT NULL DEFAULT 'genie',     -- 'genie', 'bundle', 'single'
    publisher_user_id    VARCHAR(36) NOT NULL,
    source_installation_id INTEGER,
    profile_count   INTEGER DEFAULT 0,
    collection_count INTEGER DEFAULT 0,
    coordinator_tag VARCHAR(50),
    profile_tags    TEXT,                                      -- JSON array
    manifest_summary TEXT,                                     -- JSON manifest preview
    file_path       TEXT NOT NULL,
    file_size_bytes INTEGER DEFAULT 0,
    visibility      VARCHAR(20) DEFAULT 'public',             -- 'public' or 'unlisted'
    download_count  INTEGER DEFAULT 0,
    install_count   INTEGER DEFAULT 0,
    published_at    DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL,
    FOREIGN KEY (publisher_user_id) REFERENCES users(id),
    FOREIGN KEY (source_installation_id) REFERENCES agent_pack_installations(id) ON DELETE SET NULL
);

-- User ratings/reviews for published agent packs
CREATE TABLE IF NOT EXISTS agent_pack_ratings (
    id        VARCHAR(36) PRIMARY KEY,
    pack_id   VARCHAR(36) NOT NULL,
    user_id   VARCHAR(36) NOT NULL,
    rating    INTEGER     NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment   TEXT,
    created_at DATETIME   NOT NULL,
    updated_at DATETIME   NOT NULL,
    FOREIGN KEY (pack_id) REFERENCES marketplace_agent_packs(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_marketplace_agent_packs_publisher
    ON marketplace_agent_packs(publisher_user_id);

CREATE INDEX IF NOT EXISTS idx_marketplace_agent_packs_visibility
    ON marketplace_agent_packs(visibility);

CREATE INDEX IF NOT EXISTS idx_marketplace_agent_packs_pack_type
    ON marketplace_agent_packs(pack_type);

CREATE INDEX IF NOT EXISTS idx_marketplace_agent_packs_published_at
    ON marketplace_agent_packs(published_at);

CREATE INDEX IF NOT EXISTS idx_agent_pack_ratings_pack
    ON agent_pack_ratings(pack_id);

CREATE INDEX IF NOT EXISTS idx_agent_pack_ratings_user
    ON agent_pack_ratings(user_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_pack_ratings_unique
    ON agent_pack_ratings(pack_id, user_id);
