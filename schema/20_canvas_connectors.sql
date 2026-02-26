-- Canvas Connector Credentials (DEPRECATED)
-- Named connections are now stored in the user_credentials table via
-- encrypt_credentials() with provider key "canvas_conn_{connection_id}".
-- This table is kept for backward compatibility but is no longer used.

CREATE TABLE IF NOT EXISTS canvas_connector_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    credentials_encrypted TEXT NOT NULL,
    driver TEXT,
    label TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_canvas_connector_user_connector
    ON canvas_connector_credentials(user_id, connector_id);
