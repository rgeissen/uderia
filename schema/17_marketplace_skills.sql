-- ============================================================
-- Schema: Marketplace Skills
-- Version: 1.0
-- Description: Published skills in the intelligence
--              marketplace plus user ratings/reviews.
--              Mirrors marketplace_extensions pattern.
--              Uses Claude Code skill-compatible format
--              (skill.json + .md).
-- ============================================================

-- Registry of skills published to the marketplace
CREATE TABLE IF NOT EXISTS marketplace_skills (
    id                VARCHAR(36)  PRIMARY KEY,
    skill_id          VARCHAR(100) NOT NULL,
    name              VARCHAR(255) NOT NULL,
    description       TEXT,
    version           VARCHAR(50),
    author            VARCHAR(255),
    injection_target  VARCHAR(20)  DEFAULT 'system_prompt',  -- system_prompt | user_context
    has_params        BOOLEAN      DEFAULT 0,
    tags_json         TEXT,                                   -- JSON array of tags
    publisher_user_id VARCHAR(36)  NOT NULL,
    visibility        VARCHAR(20)  DEFAULT 'public',          -- 'public' or 'targeted'
    manifest_json     TEXT,                                   -- Full skill.json for preview
    content_hash      VARCHAR(64),                            -- SHA256 of .md content for dedup
    download_count    INTEGER      DEFAULT 0,
    install_count     INTEGER      DEFAULT 0,
    published_at      DATETIME     NOT NULL,
    updated_at        DATETIME     NOT NULL,
    FOREIGN KEY (publisher_user_id) REFERENCES users(id)
);

-- User ratings/reviews for published skills
CREATE TABLE IF NOT EXISTS skill_ratings (
    id                    VARCHAR(36)  PRIMARY KEY,
    skill_marketplace_id  VARCHAR(36)  NOT NULL,
    user_id               VARCHAR(36)  NOT NULL,
    rating                INTEGER      NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment               TEXT,
    created_at            DATETIME     NOT NULL,
    updated_at            DATETIME     NOT NULL,
    FOREIGN KEY (skill_marketplace_id) REFERENCES marketplace_skills(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_marketplace_skill_publisher
    ON marketplace_skills(publisher_user_id);

CREATE INDEX IF NOT EXISTS idx_marketplace_skill_visibility
    ON marketplace_skills(visibility);

CREATE INDEX IF NOT EXISTS idx_marketplace_skill_published_at
    ON marketplace_skills(published_at);

CREATE INDEX IF NOT EXISTS idx_skill_ratings_skill
    ON skill_ratings(skill_marketplace_id);

CREATE INDEX IF NOT EXISTS idx_skill_ratings_user
    ON skill_ratings(user_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_ratings_unique
    ON skill_ratings(skill_marketplace_id, user_id);
