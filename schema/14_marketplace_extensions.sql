-- ============================================================
-- Schema: Marketplace Extensions
-- Version: 1.0
-- Description: Published extensions in the intelligence
--              marketplace plus user ratings/reviews.
--              Mirrors marketplace_agent_packs pattern.
-- ============================================================

-- Registry of extensions published to the marketplace
CREATE TABLE IF NOT EXISTS marketplace_extensions (
    id              VARCHAR(36)  PRIMARY KEY,
    extension_id    VARCHAR(100) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    version         VARCHAR(50),
    author          VARCHAR(255),
    extension_tier  VARCHAR(20),                          -- convention, simple, standard, llm
    category        VARCHAR(50),
    requires_llm    BOOLEAN DEFAULT 0,
    publisher_user_id VARCHAR(36) NOT NULL,
    visibility      VARCHAR(20) DEFAULT 'public',         -- 'public' or 'targeted'
    manifest_json   TEXT,                                  -- Full manifest for preview
    source_hash     VARCHAR(64),                           -- SHA256 of source for dedup
    download_count  INTEGER DEFAULT 0,
    install_count   INTEGER DEFAULT 0,
    published_at    DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL,
    FOREIGN KEY (publisher_user_id) REFERENCES users(id)
);

-- User ratings/reviews for published extensions
CREATE TABLE IF NOT EXISTS extension_ratings (
    id              VARCHAR(36) PRIMARY KEY,
    extension_marketplace_id VARCHAR(36) NOT NULL,
    user_id         VARCHAR(36) NOT NULL,
    rating          INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment         TEXT,
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL,
    FOREIGN KEY (extension_marketplace_id) REFERENCES marketplace_extensions(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_marketplace_ext_publisher
    ON marketplace_extensions(publisher_user_id);

CREATE INDEX IF NOT EXISTS idx_marketplace_ext_visibility
    ON marketplace_extensions(visibility);

CREATE INDEX IF NOT EXISTS idx_marketplace_ext_category
    ON marketplace_extensions(category);

CREATE INDEX IF NOT EXISTS idx_marketplace_ext_published_at
    ON marketplace_extensions(published_at);

CREATE INDEX IF NOT EXISTS idx_ext_ratings_extension
    ON extension_ratings(extension_marketplace_id);

CREATE INDEX IF NOT EXISTS idx_ext_ratings_user
    ON extension_ratings(user_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ext_ratings_unique
    ON extension_ratings(extension_marketplace_id, user_id);
