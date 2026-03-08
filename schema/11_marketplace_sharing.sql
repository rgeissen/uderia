-- ============================================================
-- Schema: Marketplace Sharing Grants
-- Version: 1.0
-- Description: Targeted sharing of marketplace resources
--              with specific users.
-- ============================================================

-- Grants table for targeted sharing
CREATE TABLE IF NOT EXISTS marketplace_sharing_grants (
    id              VARCHAR(36)  PRIMARY KEY,
    resource_type   VARCHAR(20)  NOT NULL,          -- 'collection', 'agent_pack', 'skill', 'extension', or 'knowledge_graph'
    resource_id     VARCHAR(100) NOT NULL,           -- marketplace resource ID
    grantor_user_id VARCHAR(36)  NOT NULL,
    grantee_user_id VARCHAR(36)  NOT NULL,
    created_at      DATETIME     NOT NULL,
    FOREIGN KEY (grantor_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (grantee_user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sharing_grants_grantee
    ON marketplace_sharing_grants(grantee_user_id, resource_type);

CREATE INDEX IF NOT EXISTS idx_sharing_grants_resource
    ON marketplace_sharing_grants(resource_type, resource_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sharing_grants_unique
    ON marketplace_sharing_grants(resource_type, resource_id, grantee_user_id);
