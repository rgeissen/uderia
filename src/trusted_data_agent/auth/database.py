"""
Database connection and initialization for authentication.

Manages SQLAlchemy engine, session factory, and database initialization.
"""

import os
import logging
import importlib.util
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from trusted_data_agent.auth.models import Base

# Get logger
logger = logging.getLogger("quart.app")

# Database configuration
DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"
DATABASE_URL = os.environ.get(
    'TDA_AUTH_DB_URL',
    f'sqlite:///{DEFAULT_DB_PATH}'
)

# Create engine
# Use StaticPool for SQLite to avoid threading issues
if DATABASE_URL.startswith('sqlite'):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=os.environ.get('TDA_SQL_ECHO', 'false').lower() == 'true'
    )
    
    # Enable foreign keys for SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")    # 64MB cache
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=268435456")   # 256MB memory-mapped I/O
        cursor.close()
else:
    # PostgreSQL or other databases
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # Verify connections before using
        echo=os.environ.get('TDA_SQL_ECHO', 'false').lower() == 'true'
    )

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_database():
    """
    Initialize the database by creating all tables.
    Safe to call multiple times (won't recreate existing tables).
    
    On first initialization, creates a default admin account.
    """
    try:
        # Expose the resolved DB URL so GraphStore and other modules can find it
        from trusted_data_agent.core.config import APP_CONFIG
        APP_CONFIG.AUTH_DB_PATH = DATABASE_URL

        # Create tables with checkfirst to avoid recreating existing tables
        # For indexes that may already exist, we'll handle the error gracefully
        try:
            Base.metadata.create_all(bind=engine)
        except Exception as e:
            # Handle "index already exists" errors - this can happen with SQLite
            # when the database was partially initialized
            if "already exists" in str(e).lower():
                logger.warning(f"Some database objects already exist (expected on re-initialization): {e}")
                # Try to create only the tables that don't exist
                with engine.begin() as conn:
                    for table in Base.metadata.sorted_tables:
                        try:
                            table.create(bind=conn, checkfirst=True)
                        except Exception as table_err:
                            if "already exists" not in str(table_err).lower():
                                raise
            else:
                raise
        
        # Run schema migrations for existing installations (MUST run before any User queries)
        _run_user_table_migrations()
        _run_cost_table_migrations()
        _run_consumption_table_migrations()

        # Create collections table (for marketplace)
        _create_collections_table()

        # Create template defaults table (for template configuration)
        _create_template_defaults_table()

        # Create global settings table (for three-tier configuration)
        _create_global_settings_table()

        # Create agent packs tables (for agent pack install/uninstall tracking)
        _create_agent_packs_tables()

        # Create extensions activation table (per-user extension enablement)
        _create_extensions_table()

        # Create extension settings table (admin governance)
        _create_extension_settings_table()

        # Create marketplace extensions tables
        _create_marketplace_extensions_tables()

        # Create skills activation table (per-user skill enablement)
        _create_skills_table()

        # Create skill settings table (admin governance)
        _create_skill_settings_table()

        # Create marketplace skills tables
        _create_marketplace_skills_tables()

        # Create component tables (installed_components + profile_component_config)
        _create_components_tables()

        # Create component settings table (admin governance)
        _create_component_settings_table()

        # Create vector store settings table (admin governance per tier)
        _create_vectorstore_settings_table()

        # Create knowledge graph tables (kg_entities + kg_relationships)
        _create_knowledge_graph_tables()

        # Create marketplace knowledge graph tables
        _create_marketplace_knowledge_graph_tables()

        # Create canvas connector credentials table
        _create_canvas_connector_tables()

        # Create platform MCP server registry tables (admin-governed capability servers)
        _create_platform_mcp_tables()

        # Create scheduled tasks tables (Track B — autonomous scheduling)
        _create_scheduled_tasks_tables()

        # Scheduler enhancements: platform jobs + independent scheduler gates
        _create_scheduler_enhancements()

        # Per-user component access override table
        _create_user_component_settings_table()

        # Create SSO / OIDC configuration tables (Phase 1 SSO)
        _create_sso_tables()

        # Create SAML 2.0 + group-sync tables (Phase 2 / Phase 3 SSO)
        _create_saml_tables()

        # Knowledge repository CDC fields (ingest_epoch, source_uri, sync controls)
        _run_knowledge_cdc_migrations()

        # Create default admin account if no users exist
        _create_default_admin_if_needed()
        
        # Initialize system settings
        _initialize_default_system_settings()

        # Sync VOICE_CONVERSATION_ENABLED from tts_mode setting
        _sync_tts_mode_to_config()

        # Bootstrap TTS credentials from environment variables (if available)
        _bootstrap_tts_from_env()

        # Initialize document upload configurations
        _initialize_document_upload_configs()
        
        # Bootstrap consumption profiles from tda_config.json
        _bootstrap_consumption_profiles()

        # Bootstrap prompt management system
        _bootstrap_prompt_system()

        # Sync any new provider mappings added to tda_config.json after initial bootstrap
        _sync_default_prompt_mappings()

        # Bootstrap recommended models from tda_config.json
        _bootstrap_recommended_models()

        # Bootstrap provider-available models (e.g., Friendli serverless)
        _bootstrap_provider_models()

        return True
    except Exception as e:
        logger.error(f"Failed to initialize authentication database: {e}", exc_info=True)
        return False


def _create_collections_table():
    """
    Create the collections table for the marketplace feature.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3
    
    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()
        
        # Create collections table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL,
                collection_name VARCHAR(255) NOT NULL UNIQUE,
                mcp_server_id VARCHAR(100),
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                description TEXT,
                owner_user_id VARCHAR(36) NOT NULL,
                visibility VARCHAR(20) NOT NULL DEFAULT 'private',
                is_marketplace_listed BOOLEAN NOT NULL DEFAULT 0,
                subscriber_count INTEGER NOT NULL DEFAULT 0,
                marketplace_category VARCHAR(50),
                marketplace_tags TEXT,
                marketplace_long_description TEXT,
                repository_type TEXT DEFAULT 'planner',
                chunking_strategy TEXT DEFAULT 'none',
                chunk_size INTEGER DEFAULT 1000,
                chunk_overlap INTEGER DEFAULT 200,
                embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
                document_count INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                search_mode TEXT DEFAULT 'semantic',
                hybrid_keyword_weight REAL DEFAULT 0.3,
                FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_collections_owner ON collections(owner_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_collections_marketplace ON collections(is_marketplace_listed, visibility)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_collections_name ON collections(collection_name)")

        # Migration: Add embedding_model column if it doesn't exist
        try:
            cursor.execute("SELECT embedding_model FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            logger.info("Adding embedding_model column to collections table")
            cursor.execute("ALTER TABLE collections ADD COLUMN embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2'")
            conn.commit()

        # Migration: Add backend_type/backend_config columns if they don't exist
        try:
            cursor.execute("SELECT backend_type FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding backend_type/backend_config columns to collections table")
            cursor.execute("ALTER TABLE collections ADD COLUMN backend_type TEXT DEFAULT 'chromadb'")
            cursor.execute("ALTER TABLE collections ADD COLUMN backend_config TEXT DEFAULT '{}'")
            conn.commit()

        # Migration: Add vector_store_config_id column for centralized vector store configurations
        try:
            cursor.execute("SELECT vector_store_config_id FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding vector_store_config_id column to collections table")
            cursor.execute("ALTER TABLE collections ADD COLUMN vector_store_config_id TEXT DEFAULT NULL")
            conn.commit()

        # Migration: Add document_count/chunk_count columns for persisted metadata
        try:
            cursor.execute("SELECT document_count FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding document_count and chunk_count columns to collections table")
            cursor.execute("ALTER TABLE collections ADD COLUMN document_count INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE collections ADD COLUMN chunk_count INTEGER DEFAULT 0")
            conn.commit()

        # Migration: Add search_mode / hybrid_keyword_weight columns for hybrid search
        try:
            cursor.execute("SELECT search_mode FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding search_mode and hybrid_keyword_weight columns to collections table")
            cursor.execute("ALTER TABLE collections ADD COLUMN search_mode TEXT DEFAULT 'semantic'")
            cursor.execute("ALTER TABLE collections ADD COLUMN hybrid_keyword_weight REAL DEFAULT 0.3")
            conn.commit()

        # Migration: Add server-side chunking params for Teradata EVS collections
        try:
            cursor.execute("SELECT optimized_chunking FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding server-side chunking columns to collections table")
            cursor.execute("ALTER TABLE collections ADD COLUMN optimized_chunking INTEGER DEFAULT 1")
            cursor.execute("ALTER TABLE collections ADD COLUMN ss_chunk_size INTEGER DEFAULT 2000")
            cursor.execute("ALTER TABLE collections ADD COLUMN header_height INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE collections ADD COLUMN footer_height INTEGER DEFAULT 0")
            conn.commit()

        # Fix legacy NULL backend_type values
        cursor.execute("UPDATE collections SET backend_type = 'chromadb' WHERE backend_type IS NULL")
        if cursor.rowcount > 0:
            logger.info(f"Fixed NULL backend_type for {cursor.rowcount} legacy collections")
            conn.commit()

        # Create document_chunks table for Knowledge repositories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                document_id TEXT NOT NULL,
                chunk_id TEXT UNIQUE NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                embedding_model TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (collection_id) REFERENCES collections (id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks_collection ON document_chunks(collection_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks_document ON document_chunks(document_id)")
        
        # Create knowledge_documents table for tracking original documents
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                document_id TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                document_type TEXT,
                title TEXT,
                author TEXT,
                source TEXT,
                category TEXT,
                tags TEXT,
                file_size INTEGER,
                page_count INTEGER,
                content_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                metadata TEXT,
                FOREIGN KEY (collection_id) REFERENCES collections (id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_docs_collection ON knowledge_documents(collection_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_docs_category ON knowledge_documents(category)")

        # Backfill document_count from knowledge_documents for existing repos
        # (runs after knowledge_documents table is guaranteed to exist)
        cursor.execute("""
            UPDATE collections SET document_count = (
                SELECT COUNT(*) FROM knowledge_documents kd WHERE kd.collection_id = collections.id
            )
            WHERE repository_type = 'knowledge' AND document_count = 0
            AND EXISTS (SELECT 1 FROM knowledge_documents kd WHERE kd.collection_id = collections.id)
        """)
        if cursor.rowcount > 0:
            logger.info(f"Backfilled document_count for {cursor.rowcount} existing knowledge repositories")
            conn.commit()

        # Create collection_subscriptions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collection_subscriptions (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                source_collection_id INTEGER NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                subscribed_at DATETIME NOT NULL,
                last_synced_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (source_collection_id) REFERENCES collections(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_subscription_user_collection ON collection_subscriptions(user_id, source_collection_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscription_user ON collection_subscriptions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscription_collection ON collection_subscriptions(source_collection_id)")
        
        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating collections table: {e}", exc_info=True)
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass


def _create_template_defaults_table():
    """
    Create the template_defaults table for storing user/system template parameter overrides.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3
    
    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()
        
        # Create template_defaults table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS template_defaults (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id VARCHAR(100) NOT NULL,
                user_id VARCHAR(36),
                parameter_name VARCHAR(100) NOT NULL,
                parameter_value TEXT NOT NULL,
                parameter_type VARCHAR(20) NOT NULL,
                is_system_default BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                updated_by VARCHAR(36),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL,
                UNIQUE(template_id, user_id, parameter_name)
            )
        """)
        
        # Create indexes for efficient queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_template_defaults_template ON template_defaults(template_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_template_defaults_user ON template_defaults(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_template_defaults_system ON template_defaults(is_system_default)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_template_defaults_lookup ON template_defaults(template_id, user_id)")
        
        conn.commit()
        conn.close()
        
        pass  # Template defaults initialized
        
    except Exception as e:
        logger.error(f"Error creating template defaults table: {e}", exc_info=True)


def _create_global_settings_table():
    """
    Create the genie_global_settings table for three-tier configuration.
    Stores global defaults for Genie and Knowledge settings with admin lock capability.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        # Create genie_global_settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS genie_global_settings (
                id INTEGER PRIMARY KEY,
                setting_key TEXT NOT NULL UNIQUE,
                setting_value TEXT NOT NULL,
                is_locked BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT
            )
        """)

        # Create index for quick lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_genie_settings_key ON genie_global_settings(setting_key)")

        # Insert default values for Genie settings (if not already present)
        cursor.execute("""
            INSERT OR IGNORE INTO genie_global_settings (setting_key, setting_value, is_locked) VALUES
                ('temperature', '0.7', 0),
                ('queryTimeout', '300', 0),
                ('maxIterations', '10', 0)
        """)

        # Insert default values for Knowledge settings (if not already present)
        cursor.execute("""
            INSERT OR IGNORE INTO genie_global_settings (setting_key, setting_value, is_locked) VALUES
                ('knowledge_minRelevanceScore', '0.30', 0),
                ('knowledge_maxDocs', '3', 0),
                ('knowledge_maxTokens', '2000', 0),
                ('knowledge_rerankingEnabled', '0', 0)
        """)

        conn.commit()
        conn.close()

        pass  # Global settings table initialized

    except Exception as e:
        logger.error(f"Error creating global settings table: {e}", exc_info=True)


def _create_agent_packs_tables():
    """
    Create the agent pack installation tracking tables.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "09_agent_packs.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 09_agent_packs.sql")
        else:
            # Inline fallback if schema file not found
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS agent_pack_installations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    version VARCHAR(50),
                    author VARCHAR(255),
                    coordinator_tag VARCHAR(50) NOT NULL,
                    coordinator_profile_id VARCHAR(100),
                    owner_user_id VARCHAR(36) NOT NULL,
                    installed_at DATETIME NOT NULL,
                    manifest_json TEXT NOT NULL,
                    FOREIGN KEY (owner_user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS agent_pack_resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pack_installation_id INTEGER NOT NULL,
                    resource_type VARCHAR(20) NOT NULL,
                    resource_id VARCHAR(100) NOT NULL,
                    resource_tag VARCHAR(50),
                    resource_role VARCHAR(20),
                    is_owned BOOLEAN NOT NULL DEFAULT 1,
                    FOREIGN KEY (pack_installation_id) REFERENCES agent_pack_installations(id)
                );
            """)
            logger.info("Created agent pack tables (inline fallback)")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating agent packs tables: {e}", exc_info=True)


def _create_extensions_table():
    """
    Create the per-user extension activation table.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "12_extensions.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 12_extensions.sql")
        else:
            # Inline fallback
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS user_extensions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_uuid VARCHAR(36) NOT NULL,
                    extension_id VARCHAR(100) NOT NULL,
                    activation_name VARCHAR(100) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    default_param VARCHAR(255),
                    config_json TEXT,
                    activated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_uuid) REFERENCES users(id),
                    UNIQUE(user_uuid, activation_name)
                );
                CREATE INDEX IF NOT EXISTS idx_user_extensions_user
                    ON user_extensions(user_uuid, is_active);
                CREATE INDEX IF NOT EXISTS idx_user_extensions_name
                    ON user_extensions(user_uuid, activation_name);
            """)
            logger.info("Created extensions table (inline fallback)")

        conn.commit()

        # Verify table was created successfully
        cursor.execute("SELECT COUNT(*) FROM user_extensions LIMIT 1")
        cursor.fetchone()
        logger.debug("Verified: user_extensions table is accessible")

        conn.close()

    except Exception as e:
        logger.error(f"Error creating extensions table: {e}", exc_info=True)


def _create_extension_settings_table():
    """
    Create the extension_settings table for admin extension governance.
    Bootstraps defaults from tda_config.json if available.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3
    import json
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "13_extension_settings.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 13_extension_settings.sql")
        else:
            # Inline fallback
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS extension_settings (
                    id INTEGER PRIMARY KEY,
                    setting_key TEXT NOT NULL UNIQUE,
                    setting_value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT
                );
                INSERT OR IGNORE INTO extension_settings (setting_key, setting_value) VALUES
                    ('extensions_mode', 'all'),
                    ('disabled_extensions', '[]'),
                    ('user_extensions_enabled', 'true'),
                    ('user_extensions_marketplace_enabled', 'true');
                CREATE INDEX IF NOT EXISTS idx_extension_settings_key
                    ON extension_settings(setting_key);
            """)
            logger.info("Created extension_settings table (inline fallback)")

        # Bootstrap from tda_config.json if values differ from SQL defaults
        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                ext_settings = config.get("extension_settings", {})
                if ext_settings:
                    for key, value in ext_settings.items():
                        # Convert Python types to string storage
                        if isinstance(value, bool):
                            str_value = 'true' if value else 'false'
                        elif isinstance(value, list):
                            str_value = json.dumps(value)
                        else:
                            str_value = str(value)
                        # Insert new keys, or update existing keys only if not admin-modified
                        cursor.execute(
                            """
                            INSERT INTO extension_settings (setting_key, setting_value)
                            VALUES (?, ?)
                            ON CONFLICT(setting_key) DO UPDATE
                            SET setting_value = excluded.setting_value
                            WHERE extension_settings.updated_by IS NULL
                            """,
                            (key, str_value)
                        )
                        if cursor.rowcount > 0:
                            logger.debug(f"Synced extension setting '{key}' from tda_config.json")
            except Exception as cfg_err:
                logger.warning(f"Could not bootstrap extension settings from tda_config.json: {cfg_err}")

        conn.commit()

        # Verify table was created successfully and has expected default rows
        cursor.execute("SELECT COUNT(*) FROM extension_settings")
        row_count = cursor.fetchone()[0]
        if row_count == 0:
            logger.warning("extension_settings table created but contains no default rows")
        else:
            logger.debug(f"Verified: extension_settings table accessible with {row_count} setting(s)")

        conn.close()

    except Exception as e:
        logger.error(f"Error creating extension_settings table: {e}", exc_info=True)


def _create_marketplace_extensions_tables():
    """
    Create the marketplace_extensions and extension_ratings tables.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "14_marketplace_extensions.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 14_marketplace_extensions.sql")
        else:
            # Inline fallback
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS marketplace_extensions (
                    id VARCHAR(36) PRIMARY KEY,
                    extension_id VARCHAR(100) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    version VARCHAR(50),
                    author VARCHAR(255),
                    extension_tier VARCHAR(20),
                    category VARCHAR(50),
                    requires_llm BOOLEAN DEFAULT 0,
                    publisher_user_id VARCHAR(36) NOT NULL,
                    visibility VARCHAR(20) DEFAULT 'public',
                    manifest_json TEXT,
                    source_hash VARCHAR(64),
                    download_count INTEGER DEFAULT 0,
                    install_count INTEGER DEFAULT 0,
                    published_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY (publisher_user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS extension_ratings (
                    id VARCHAR(36) PRIMARY KEY,
                    extension_marketplace_id VARCHAR(36) NOT NULL,
                    user_id VARCHAR(36) NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                    comment TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY (extension_marketplace_id) REFERENCES marketplace_extensions(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_marketplace_ext_publisher
                    ON marketplace_extensions(publisher_user_id);
                CREATE INDEX IF NOT EXISTS idx_marketplace_ext_visibility
                    ON marketplace_extensions(visibility);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ext_ratings_unique
                    ON extension_ratings(extension_marketplace_id, user_id);
            """)
            logger.info("Created marketplace_extensions tables (inline fallback)")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating marketplace_extensions tables: {e}", exc_info=True)


def _create_skills_table():
    """
    Create the per-user skill activation table.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "15_skills.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 15_skills.sql")
        else:
            # Inline fallback
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS user_skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_uuid VARCHAR(36) NOT NULL,
                    skill_id VARCHAR(100) NOT NULL,
                    activation_name VARCHAR(100) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    default_param VARCHAR(255),
                    config_json TEXT,
                    activated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_uuid) REFERENCES users(id),
                    UNIQUE(user_uuid, activation_name)
                );
                CREATE INDEX IF NOT EXISTS idx_user_skills_user
                    ON user_skills(user_uuid, is_active);
                CREATE INDEX IF NOT EXISTS idx_user_skills_name
                    ON user_skills(user_uuid, activation_name);
            """)
            logger.info("Created skills table (inline fallback)")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating skills table: {e}", exc_info=True)


def _create_skill_settings_table():
    """
    Create the skill_settings table for admin skill governance.
    Safe to call multiple times (won't recreate if exists).
    """
    import json
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "16_skill_settings.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 16_skill_settings.sql")
        else:
            # Inline fallback
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS skill_settings (
                    id INTEGER PRIMARY KEY,
                    setting_key TEXT NOT NULL UNIQUE,
                    setting_value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT OR IGNORE INTO skill_settings (setting_key, setting_value) VALUES
                    ('skills_mode', 'all'),
                    ('disabled_skills', '[]'),
                    ('user_skills_enabled', 'true'),
                    ('auto_skills_enabled', 'false');
                CREATE INDEX IF NOT EXISTS idx_skill_settings_key
                    ON skill_settings(setting_key);
            """)
            logger.info("Created skill_settings table (inline fallback)")

        # Bootstrap from tda_config.json if values differ from SQL defaults
        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                skill_settings = config.get("skill_settings", {})
                if skill_settings:
                    for key, value in skill_settings.items():
                        if isinstance(value, bool):
                            str_value = 'true' if value else 'false'
                        elif isinstance(value, list):
                            str_value = json.dumps(value)
                        else:
                            str_value = str(value)
                        cursor.execute(
                            """
                            INSERT INTO skill_settings (setting_key, setting_value)
                            VALUES (?, ?)
                            ON CONFLICT(setting_key) DO UPDATE
                            SET setting_value = excluded.setting_value
                            """,
                            (key, str_value)
                        )
                        if cursor.rowcount > 0:
                            logger.debug(f"Synced skill setting '{key}' from tda_config.json")
            except Exception as cfg_err:
                logger.warning(f"Could not bootstrap skill settings from tda_config.json: {cfg_err}")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating skill_settings table: {e}", exc_info=True)


def _create_marketplace_skills_tables():
    """
    Create marketplace_skills and skill_ratings tables.
    Safe to call multiple times (won't recreate if exists).
    Mirrors _create_marketplace_extensions_tables().
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "17_marketplace_skills.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 17_marketplace_skills.sql")
        else:
            # Inline fallback
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS marketplace_skills (
                    id VARCHAR(36) PRIMARY KEY,
                    skill_id VARCHAR(100) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    version VARCHAR(50),
                    author VARCHAR(255),
                    injection_target VARCHAR(20) DEFAULT 'system_prompt',
                    has_params BOOLEAN DEFAULT 0,
                    tags_json TEXT,
                    publisher_user_id VARCHAR(36) NOT NULL,
                    visibility VARCHAR(20) DEFAULT 'public',
                    manifest_json TEXT,
                    content_hash VARCHAR(64),
                    download_count INTEGER DEFAULT 0,
                    install_count INTEGER DEFAULT 0,
                    published_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY (publisher_user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS skill_ratings (
                    id VARCHAR(36) PRIMARY KEY,
                    skill_marketplace_id VARCHAR(36) NOT NULL,
                    user_id VARCHAR(36) NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                    comment TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY (skill_marketplace_id) REFERENCES marketplace_skills(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_marketplace_skill_publisher
                    ON marketplace_skills(publisher_user_id);
                CREATE INDEX IF NOT EXISTS idx_marketplace_skill_visibility
                    ON marketplace_skills(visibility);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_ratings_unique
                    ON skill_ratings(skill_marketplace_id, user_id);
            """)
            logger.info("Created marketplace_skills tables (inline fallback)")

        # Ensure marketplace setting exists in skill_settings
        cursor.execute(
            "INSERT OR IGNORE INTO skill_settings (setting_key, setting_value) "
            "VALUES ('user_skills_marketplace_enabled', 'true')"
        )

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating marketplace_skills tables: {e}", exc_info=True)


def _create_components_tables():
    """
    Create installed_components table for component registry.
    Per-profile component config lives on the profile JSON dict (componentConfig key),
    not in a separate DB table.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "18_components.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 18_components.sql")
        else:
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS installed_components (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component_id TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    source TEXT NOT NULL DEFAULT 'builtin',
                    agent_pack_id TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    manifest_json TEXT,
                    installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_installed_components_source
                    ON installed_components(source);
                CREATE INDEX IF NOT EXISTS idx_installed_components_active
                    ON installed_components(is_active);
            """)
            logger.info("Created components tables (inline fallback)")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating components tables: {e}", exc_info=True)


def _create_component_settings_table():
    """
    Create component_settings table for admin governance.
    Safe to call multiple times (won't recreate if exists).
    Mirrors _create_extension_settings_table().
    """
    import json
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "19_component_settings.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 19_component_settings.sql")
        else:
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS component_settings (
                    id INTEGER PRIMARY KEY,
                    setting_key TEXT NOT NULL UNIQUE,
                    setting_value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT
                );
                INSERT OR IGNORE INTO component_settings (setting_key, setting_value) VALUES
                    ('components_mode', 'all'),
                    ('disabled_components', '[]'),
                    ('user_components_enabled', 'true'),
                    ('user_components_marketplace_enabled', 'true');
                CREATE INDEX IF NOT EXISTS idx_component_settings_key
                    ON component_settings(setting_key);
            """)
            logger.info("Created component_settings table (inline fallback)")

        # Bootstrap from tda_config.json if component_settings exists
        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                component_settings = config.get("component_settings", {})
                if component_settings:
                    for key, value in component_settings.items():
                        if isinstance(value, bool):
                            str_value = 'true' if value else 'false'
                        elif isinstance(value, list):
                            str_value = json.dumps(value)
                        else:
                            str_value = str(value)
                        cursor.execute(
                            """
                            INSERT INTO component_settings (setting_key, setting_value)
                            VALUES (?, ?)
                            ON CONFLICT(setting_key) DO NOTHING
                            """,
                            (key, str_value)
                        )
            except Exception as cfg_err:
                logger.warning(f"Could not bootstrap component settings from tda_config.json: {cfg_err}")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating component_settings table: {e}", exc_info=True)


def _create_vectorstore_settings_table():
    """
    Create vectorstore_settings table for admin governance of vector store backends.
    Controls which backends are available per user tier for knowledge repository creation.
    Safe to call multiple times (won't recreate if exists).
    Mirrors _create_component_settings_table().
    """
    import json
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "24_vectorstore_settings.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 24_vectorstore_settings.sql")
        else:
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS vectorstore_settings (
                    id INTEGER PRIMARY KEY,
                    setting_key TEXT NOT NULL UNIQUE,
                    setting_value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT
                );
                INSERT OR IGNORE INTO vectorstore_settings (setting_key, setting_value) VALUES
                    ('allowed_backends_user', '["chromadb","teradata","qdrant"]'),
                    ('allowed_backends_developer', '["chromadb","teradata","qdrant"]');
                CREATE INDEX IF NOT EXISTS idx_vectorstore_settings_key
                    ON vectorstore_settings(setting_key);
            """)
            logger.info("Created vectorstore_settings table (inline fallback)")

        # Bootstrap from tda_config.json if vectorstore_settings key exists
        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                vectorstore_settings = config.get("vectorstore_settings", {})
                if vectorstore_settings:
                    for key, value in vectorstore_settings.items():
                        if isinstance(value, list):
                            str_value = json.dumps(value)
                        else:
                            str_value = str(value)
                        cursor.execute(
                            """
                            INSERT INTO vectorstore_settings (setting_key, setting_value)
                            VALUES (?, ?)
                            ON CONFLICT(setting_key) DO NOTHING
                            """,
                            (key, str_value)
                        )
            except Exception as cfg_err:
                logger.warning(f"Could not bootstrap vectorstore settings from tda_config.json: {cfg_err}")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating vectorstore_settings table: {e}", exc_info=True)


def _create_knowledge_graph_tables():
    """
    Create kg_entities and kg_relationships tables for the Knowledge Graph component.
    Scoped per (profile_id, user_uuid) for multi-user isolation.
    Safe to call multiple times (won't recreate if exists).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        # Enable foreign key enforcement for CASCADE deletes
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "21_knowledge_graph.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 21_knowledge_graph.sql")
        else:
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS kg_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id TEXT NOT NULL,
                    user_uuid TEXT NOT NULL,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    properties_json TEXT DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_detail TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(profile_id, user_uuid, name, entity_type)
                );
                CREATE TABLE IF NOT EXISTS kg_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id TEXT NOT NULL,
                    user_uuid TEXT NOT NULL,
                    source_entity_id INTEGER NOT NULL,
                    target_entity_id INTEGER NOT NULL,
                    relationship_type TEXT NOT NULL,
                    cardinality TEXT,
                    metadata_json TEXT DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
                    UNIQUE(profile_id, user_uuid, source_entity_id, target_entity_id, relationship_type)
                );
                CREATE INDEX IF NOT EXISTS idx_kg_entities_profile_user
                    ON kg_entities(profile_id, user_uuid);
                CREATE INDEX IF NOT EXISTS idx_kg_entities_type
                    ON kg_entities(profile_id, user_uuid, entity_type);
                CREATE INDEX IF NOT EXISTS idx_kg_entities_name
                    ON kg_entities(profile_id, user_uuid, name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_kg_relationships_profile_user
                    ON kg_relationships(profile_id, user_uuid);
                CREATE INDEX IF NOT EXISTS idx_kg_relationships_source
                    ON kg_relationships(source_entity_id);
                CREATE INDEX IF NOT EXISTS idx_kg_relationships_target
                    ON kg_relationships(target_entity_id);
                CREATE INDEX IF NOT EXISTS idx_kg_relationships_type
                    ON kg_relationships(profile_id, user_uuid, relationship_type);
            """)
            logger.info("Created knowledge graph tables (inline fallback)")

        # --- KG Profile Assignments (1:* mapping + active/inactive state) ---
        # Step 1: Ensure the base table exists (without the is_active-dependent index)
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS kg_profile_assignments (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                kg_id               TEXT,
                kg_owner_profile_id TEXT NOT NULL,
                assigned_profile_id TEXT NOT NULL,
                user_uuid           TEXT NOT NULL,
                is_active           BOOLEAN DEFAULT 0 CHECK(is_active IN (0, 1)),
                UNIQUE(kg_id, assigned_profile_id, user_uuid)
            );
            CREATE INDEX IF NOT EXISTS idx_kg_assignments_assigned
                ON kg_profile_assignments(assigned_profile_id, user_uuid);
            CREATE INDEX IF NOT EXISTS idx_kg_assignments_owner
                ON kg_profile_assignments(kg_owner_profile_id, user_uuid);
        """)

        # Step 2: Migration — add is_active column if missing (existing tables from v1.0)
        try:
            cursor.execute("SELECT is_active FROM kg_profile_assignments LIMIT 1")
        except Exception:
            try:
                cursor.execute("ALTER TABLE kg_profile_assignments ADD COLUMN is_active BOOLEAN DEFAULT 0 CHECK(is_active IN (0, 1))")
                conn.commit()
                logger.info("Migrated kg_profile_assignments: added is_active column")
            except Exception as migrate_err:
                logger.debug(f"kg_profile_assignments migration (is_active) skipped: {migrate_err}")

        # Step 3: Create the partial unique index (requires is_active column to exist)
        try:
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_one_active_per_profile
                    ON kg_profile_assignments(assigned_profile_id, user_uuid) WHERE is_active = 1
            """)
        except Exception:
            pass  # Index may already exist or column still missing in edge case

        # Multi-KG migration: add kg_id scope key to entities/relationships
        _migrate_to_multi_kg(conn)

        # Fix kg_profile_assignments unique constraint (runs independently of _migrate_to_multi_kg guard).
        # Guard: 'created_at' column is only present in the old schema; new schema omits it.
        _migrate_kg_assignments_constraint(conn)

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating knowledge graph tables: {e}", exc_info=True)


def _migrate_to_multi_kg(conn) -> None:
    """
    One-time migration: adds kg_id as the scope key for kg_entities and kg_relationships.

    Before:   entities scoped by (profile_id, user_uuid) → one KG per profile
    After:    entities scoped by kg_id (UUID) → many KGs per profile

    Guard:    skipped silently if kg_entities already has a kg_id column.
    Backfill: existing entities receive kg_id from kg_metadata if available,
              else profile_id is used as a synthetic kg_id (backwards-compatible).
    """
    from datetime import datetime, timezone

    cursor = conn.cursor()

    # ── Guard ────────────────────────────────────────────────────────────────
    try:
        cursor.execute("SELECT kg_id FROM kg_entities LIMIT 1")
        return  # Already migrated
    except Exception:
        pass  # kg_id column missing → proceed

    logger.info("[KG Migration] Starting multi-KG architecture migration …")
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        # ── 1. Recreate kg_metadata with new schema ───────────────────────
        # New schema removes UNIQUE(profile_id, user_uuid) and adds is_active.
        cursor.execute("""
            CREATE TABLE kg_metadata_new (
                kg_id         TEXT PRIMARY KEY,
                profile_id    TEXT NOT NULL,
                user_uuid     TEXT NOT NULL,
                name          TEXT NOT NULL,
                database_name TEXT,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)
        try:
            # Copy any existing rows; COALESCE handles old tables missing is_active
            cursor.execute("""
                INSERT OR IGNORE INTO kg_metadata_new
                    (kg_id, profile_id, user_uuid, name, database_name, is_active, created_at, updated_at)
                SELECT kg_id, profile_id, user_uuid, name, database_name,
                       COALESCE(is_active, 1), created_at, updated_at
                FROM kg_metadata
            """)
        except Exception:
            pass  # kg_metadata didn't exist yet — that's fine
        cursor.execute("DROP TABLE IF EXISTS kg_metadata")
        cursor.execute("ALTER TABLE kg_metadata_new RENAME TO kg_metadata")
        conn.commit()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_metadata_profile_user ON kg_metadata(profile_id, user_uuid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_metadata_active ON kg_metadata(profile_id, user_uuid, is_active)")
        conn.commit()
        logger.info("[KG Migration] kg_metadata: new schema applied")

        # ── 2. Synthetic kg_metadata for profiles without a metadata row ──
        now = datetime.now(timezone.utc).isoformat()
        orphan_profiles = cursor.execute("""
            SELECT DISTINCT e.profile_id, e.user_uuid FROM kg_entities e
            WHERE NOT EXISTS (
                SELECT 1 FROM kg_metadata km
                WHERE km.profile_id = e.profile_id AND km.user_uuid = e.user_uuid
            )
        """).fetchall()
        for pid, uuid in orphan_profiles:
            # Use profile_id as synthetic kg_id — preserves all existing references
            cursor.execute(
                "INSERT OR IGNORE INTO kg_metadata "
                "(kg_id, profile_id, user_uuid, name, database_name, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (pid, pid, uuid, "Imported Graph", None, now, now),
            )
        conn.commit()
        if orphan_profiles:
            logger.info(f"[KG Migration] Created synthetic kg_metadata for {len(orphan_profiles)} profile(s)")

        # ── 3. Recreate kg_entities with kg_id ────────────────────────────
        cursor.execute("""
            CREATE TABLE kg_entities_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                kg_id         TEXT NOT NULL DEFAULT '',
                profile_id    TEXT NOT NULL,
                user_uuid     TEXT NOT NULL,
                name          TEXT NOT NULL,
                entity_type   TEXT NOT NULL,
                properties_json TEXT DEFAULT '{}',
                source        TEXT NOT NULL DEFAULT 'manual',
                source_detail TEXT,
                created_at    TEXT,
                updated_at    TEXT,
                UNIQUE(kg_id, name, entity_type)
            )
        """)
        cursor.execute("""
            INSERT INTO kg_entities_new
                (id, kg_id, profile_id, user_uuid, name, entity_type,
                 properties_json, source, source_detail, created_at, updated_at)
            SELECT e.id,
                COALESCE(
                    (SELECT km.kg_id FROM kg_metadata km
                     WHERE km.profile_id = e.profile_id AND km.user_uuid = e.user_uuid
                     LIMIT 1),
                    e.profile_id
                ),
                e.profile_id, e.user_uuid, e.name, e.entity_type,
                e.properties_json, e.source, e.source_detail,
                e.created_at, e.updated_at
            FROM kg_entities e
        """)
        cursor.execute("DROP TABLE kg_entities")
        cursor.execute("ALTER TABLE kg_entities_new RENAME TO kg_entities")
        conn.commit()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_kg_id ON kg_entities(kg_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_profile_user ON kg_entities(profile_id, user_uuid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(kg_id, entity_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities(kg_id, name COLLATE NOCASE)")
        conn.commit()
        logger.info("[KG Migration] kg_entities: added kg_id column, unique constraint updated")

        # ── 4. Recreate kg_relationships with kg_id ───────────────────────
        cursor.execute("""
            CREATE TABLE kg_relationships_new (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                kg_id                TEXT NOT NULL DEFAULT '',
                profile_id           TEXT NOT NULL,
                user_uuid            TEXT NOT NULL,
                source_entity_id     INTEGER NOT NULL,
                target_entity_id     INTEGER NOT NULL,
                relationship_type    TEXT NOT NULL,
                cardinality          TEXT,
                metadata_json        TEXT DEFAULT '{}',
                source               TEXT NOT NULL DEFAULT 'manual',
                created_at           TEXT,
                FOREIGN KEY (source_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
                FOREIGN KEY (target_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
                UNIQUE(kg_id, source_entity_id, target_entity_id, relationship_type)
            )
        """)
        # Backfill kg_id from the (already migrated) kg_entities table
        cursor.execute("""
            INSERT INTO kg_relationships_new
                (id, kg_id, profile_id, user_uuid, source_entity_id, target_entity_id,
                 relationship_type, cardinality, metadata_json, source, created_at)
            SELECT r.id,
                COALESCE(e.kg_id, r.profile_id),
                r.profile_id, r.user_uuid, r.source_entity_id, r.target_entity_id,
                r.relationship_type, r.cardinality, r.metadata_json, r.source, r.created_at
            FROM kg_relationships r
            LEFT JOIN kg_entities e ON r.source_entity_id = e.id
        """)
        cursor.execute("DROP TABLE kg_relationships")
        cursor.execute("ALTER TABLE kg_relationships_new RENAME TO kg_relationships")
        conn.commit()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_kg_id ON kg_relationships(kg_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_profile_user ON kg_relationships(profile_id, user_uuid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_source ON kg_relationships(source_entity_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_target ON kg_relationships(target_entity_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_relationships_type ON kg_relationships(kg_id, relationship_type)")
        conn.commit()
        logger.info("[KG Migration] kg_relationships: added kg_id column, unique constraint updated")

        # ── 5. Add kg_id to kg_profile_assignments ────────────────────────
        try:
            cursor.execute("SELECT kg_id FROM kg_profile_assignments LIMIT 1")
        except Exception:
            try:
                cursor.execute("ALTER TABLE kg_profile_assignments ADD COLUMN kg_id TEXT")
                conn.commit()
                cursor.execute("""
                    UPDATE kg_profile_assignments SET kg_id = COALESCE(
                        (SELECT km.kg_id FROM kg_metadata km
                         WHERE km.profile_id = kg_profile_assignments.kg_owner_profile_id
                           AND km.user_uuid = kg_profile_assignments.user_uuid
                           AND km.is_active = 1
                         LIMIT 1),
                        kg_owner_profile_id
                    )
                """)
                conn.commit()
                logger.info("[KG Migration] kg_profile_assignments: added and backfilled kg_id column")
            except Exception as assign_err:
                logger.debug(f"[KG Migration] kg_profile_assignments kg_id migration skipped: {assign_err}")

        logger.info("[KG Migration] Migration complete ✓")

    except Exception as e:
        logger.error(f"[KG Migration] Failed: {e}", exc_info=True)
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()


def _migrate_kg_assignments_constraint(conn) -> None:
    """
    Fix the unique constraint on kg_profile_assignments so that a profile can be
    assigned to MULTIPLE knowledge graphs owned by the same owner profile.

    Old constraint: UNIQUE(kg_owner_profile_id, assigned_profile_id, user_uuid)
      → only one assignment per (owner, assigned_profile) regardless of KG — INSERT OR IGNORE
        silently drops the second assignment when assigning the same profile to a second KG.

    New constraint: UNIQUE(kg_id, assigned_profile_id, user_uuid)
      → one assignment per (kg, assigned_profile) — correct multi-KG semantics.

    Guard: 'created_at' column only exists in the old schema (it was never in the new one).
    This function is safe to call on every startup; it is a no-op once migrated.
    """
    try:
        cursor = conn.cursor()
        col_names = [row[1] for row in cursor.execute(
            "PRAGMA table_info(kg_profile_assignments)"
        ).fetchall()]

        if 'created_at' not in col_names:
            return  # Already on new schema

        logger.info("[KG Migration] Updating kg_profile_assignments unique constraint …")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.commit()

        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS kg_profile_assignments_v2 (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                kg_id               TEXT,
                kg_owner_profile_id TEXT NOT NULL,
                assigned_profile_id TEXT NOT NULL,
                user_uuid           TEXT NOT NULL,
                is_active           BOOLEAN NOT NULL DEFAULT 0
                                    CHECK(is_active IN (0, 1)),
                UNIQUE(kg_id, assigned_profile_id, user_uuid)
            );
            INSERT OR IGNORE INTO kg_profile_assignments_v2
                (id, kg_id, kg_owner_profile_id, assigned_profile_id, user_uuid, is_active)
            SELECT id, kg_id, kg_owner_profile_id, assigned_profile_id, user_uuid,
                   COALESCE(is_active, 0)
            FROM kg_profile_assignments;
            DROP TABLE kg_profile_assignments;
            ALTER TABLE kg_profile_assignments_v2 RENAME TO kg_profile_assignments;
            CREATE INDEX IF NOT EXISTS idx_kg_assignments_assigned
                ON kg_profile_assignments(assigned_profile_id, user_uuid);
            CREATE INDEX IF NOT EXISTS idx_kg_assignments_owner
                ON kg_profile_assignments(kg_owner_profile_id, user_uuid);
        """)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        logger.info("[KG Migration] kg_profile_assignments: constraint updated to UNIQUE(kg_id, assigned_profile_id, user_uuid)")
    except Exception as e:
        logger.warning(f"[KG Migration] kg_profile_assignments constraint migration failed: {e}")


def _create_marketplace_knowledge_graph_tables():
    """
    Create marketplace_knowledge_graphs, knowledge_graph_ratings, and kg_marketplace_settings tables.
    Safe to call multiple times (won't recreate if exists).
    Mirrors _create_marketplace_skills_tables().
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "23_marketplace_knowledge_graphs.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 23_marketplace_knowledge_graphs.sql")
        else:
            # Inline fallback
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS marketplace_knowledge_graphs (
                    id VARCHAR(36) PRIMARY KEY,
                    source_profile_id TEXT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    version VARCHAR(50),
                    author VARCHAR(255),
                    domain VARCHAR(100),
                    entity_count INTEGER DEFAULT 0,
                    relationship_count INTEGER DEFAULT 0,
                    entity_types_json TEXT,
                    relationship_types_json TEXT,
                    tags_json TEXT,
                    publisher_user_id VARCHAR(36) NOT NULL,
                    visibility VARCHAR(20) DEFAULT 'public',
                    manifest_json TEXT,
                    content_hash VARCHAR(64),
                    download_count INTEGER DEFAULT 0,
                    install_count INTEGER DEFAULT 0,
                    published_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY (publisher_user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_graph_ratings (
                    id VARCHAR(36) PRIMARY KEY,
                    kg_marketplace_id VARCHAR(36) NOT NULL,
                    user_id VARCHAR(36) NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                    comment TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY (kg_marketplace_id) REFERENCES marketplace_knowledge_graphs(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS kg_marketplace_settings (
                    id INTEGER PRIMARY KEY,
                    setting_key TEXT NOT NULL UNIQUE,
                    setting_value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT OR IGNORE INTO kg_marketplace_settings (setting_key, setting_value) VALUES
                    ('kg_marketplace_enabled', 'true');
                CREATE INDEX IF NOT EXISTS idx_marketplace_kg_publisher
                    ON marketplace_knowledge_graphs(publisher_user_id);
                CREATE INDEX IF NOT EXISTS idx_marketplace_kg_visibility
                    ON marketplace_knowledge_graphs(visibility);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_ratings_unique
                    ON knowledge_graph_ratings(kg_marketplace_id, user_id);
            """)
            logger.info("Created marketplace_knowledge_graphs tables (inline fallback)")

        # Migration: add kg_id column if not present
        try:
            cursor.execute("SELECT kg_id FROM marketplace_knowledge_graphs LIMIT 0")
        except Exception:
            cursor.execute("ALTER TABLE marketplace_knowledge_graphs ADD COLUMN kg_id TEXT")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_marketplace_kg_kg_id ON marketplace_knowledge_graphs(kg_id)")
            logger.info("Migrated marketplace_knowledge_graphs: added kg_id column")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating marketplace_knowledge_graphs tables: {e}", exc_info=True)


def _create_canvas_connector_tables():
    """
    DEPRECATED: Canvas connections are now stored in the user_credentials
    table via encrypt_credentials() with provider key "canvas_conn_{id}".
    This function is kept as a no-op for backward compatibility with the
    schema file (20_canvas_connectors.sql creates a legacy table that is
    no longer read or written by the application).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "20_canvas_connectors.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 20_canvas_connectors.sql (legacy table)")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating canvas connector tables: {e}", exc_info=True)


def _create_platform_mcp_tables():
    """
    Create platform connector registry tables.
    These tables govern admin-installed capability servers (browser, files, shell, web, google)
    and are strictly separate from user-configured data source servers.
    Safe to call multiple times (CREATE TABLE IF NOT EXISTS).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "27_platform_mcp_servers.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                cursor.executescript(f.read())
        else:
            logger.warning("Schema file 27_platform_mcp_servers.sql not found — skipping")

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating platform connector tables: {e}", exc_info=True)


def _create_scheduled_tasks_tables():
    """
    Create scheduled task tables for the autonomous scheduling component (Track B).
    Safe to call multiple times (CREATE TABLE IF NOT EXISTS).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "28_scheduled_tasks.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 28_scheduled_tasks.sql")
        else:
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id TEXT PRIMARY KEY,
                    user_uuid TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    session_id TEXT,
                    last_run_at TEXT,
                    last_run_status TEXT,
                    next_run_at TEXT,
                    output_channel TEXT,
                    output_config TEXT,
                    max_tokens_per_run INTEGER,
                    overlap_policy TEXT DEFAULT 'skip',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS scheduled_task_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
                    bg_task_id TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    status TEXT,
                    skip_reason TEXT,
                    result_summary TEXT,
                    tokens_used INTEGER,
                    cost_usd REAL
                );
                CREATE TABLE IF NOT EXISTS messaging_identities (
                    user_uuid TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    platform_user_id TEXT NOT NULL,
                    access_token TEXT,
                    refresh_token TEXT,
                    token_expiry TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (user_uuid, platform)
                );
            """)
            logger.info("Created scheduled_tasks tables (inline fallback)")

        conn.commit()
        conn.close()

        # Run column migrations after schema is guaranteed to exist
        try:
            from trusted_data_agent.core.task_scheduler import _ensure_columns
            _ensure_columns()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error creating scheduled_tasks tables: {e}", exc_info=True)


def _create_scheduler_enhancements():
    """
    Apply scheduler enhancements: seed platform maintenance jobs and add independent
    scheduler gate settings to component_settings. The job_type column migration is
    handled by task_scheduler._ensure_columns() which runs before this.
    Safe to call multiple times (INSERT OR IGNORE throughout).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()
        schema_path = Path(__file__).resolve().parents[3] / "schema" / "33_scheduler_enhancements.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            # Run only INSERT statements (safe on any install state); skip comment lines
            for statement in sql.split(';'):
                stmt = statement.strip()
                if stmt and not stmt.startswith('--'):
                    try:
                        cursor.execute(stmt)
                    except Exception:
                        pass
            conn.commit()
            logger.debug("Applied schema: 33_scheduler_enhancements.sql")
        conn.close()
    except Exception as e:
        logger.error(f"Error applying scheduler enhancements: {e}", exc_info=True)


def _create_user_component_settings_table():
    """
    Create user_component_settings table for per-user component access overrides.
    Admin can explicitly grant or block individual users from using specific components.
    Safe to call multiple times (CREATE TABLE IF NOT EXISTS).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()
        schema_path = Path(__file__).resolve().parents[3] / "schema" / "34_user_component_settings.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                sql = f.read()
            cursor.executescript(sql)
            logger.debug("Applied schema: 34_user_component_settings.sql")
        else:
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS user_component_settings (
                    id          INTEGER PRIMARY KEY,
                    user_uuid   TEXT NOT NULL,
                    component_id TEXT NOT NULL,
                    is_enabled  INTEGER NOT NULL DEFAULT 1,
                    note        TEXT,
                    updated_at  TEXT DEFAULT (datetime('now')),
                    updated_by  TEXT,
                    UNIQUE(user_uuid, component_id)
                );
                CREATE INDEX IF NOT EXISTS idx_ucs_user_uuid
                    ON user_component_settings(user_uuid);
                CREATE INDEX IF NOT EXISTS idx_ucs_component_id
                    ON user_component_settings(component_id);
            """)
            logger.info("Created user_component_settings table (inline fallback)")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error creating user_component_settings table: {e}", exc_info=True)


def _create_sso_tables():
    """
    Create SSO / OIDC configuration tables and add SSO columns to users.
    Safe to call multiple times (CREATE TABLE IF NOT EXISTS + ALTER TABLE checks).
    """
    import sqlite3
    from pathlib import Path

    try:
        conn = sqlite3.connect(DATABASE_URL.replace('sqlite:///', ''))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "30_sso.sql"
        if schema_path.exists():
            with open(schema_path, 'r') as f:
                cursor.executescript(f.read())
            logger.debug("Applied schema: 30_sso.sql")
        else:
            # Inline fallback
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS sso_configurations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'oidc',
                    issuer_url TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    client_secret TEXT NOT NULL,
                    discovery_doc TEXT,
                    discovery_cached_at TEXT,
                    scopes TEXT NOT NULL DEFAULT '["openid","profile","email"]',
                    email_claim TEXT NOT NULL DEFAULT 'email',
                    name_claim TEXT NOT NULL DEFAULT 'name',
                    groups_claim TEXT,
                    sub_claim TEXT NOT NULL DEFAULT 'sub',
                    group_tier_map TEXT,
                    default_tier TEXT NOT NULL DEFAULT 'user',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    auto_provision_users INTEGER NOT NULL DEFAULT 1,
                    require_email_verification INTEGER NOT NULL DEFAULT 0,
                    display_order INTEGER NOT NULL DEFAULT 0,
                    button_label TEXT,
                    icon_url TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS sso_sessions (
                    id TEXT PRIMARY KEY,
                    user_uuid TEXT NOT NULL,
                    sso_config_id TEXT NOT NULL,
                    id_token_hash TEXT NOT NULL,
                    sid TEXT,
                    sub TEXT NOT NULL,
                    issued_at TEXT NOT NULL DEFAULT (datetime('now')),
                    expires_at TEXT,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    revoked_at TEXT
                );
            """)

        # Migrate users table: add SSO columns if not present
        sso_columns = [
            ("auth_method", "TEXT"),
            ("sso_config_id", "TEXT"),
            ("sso_session_id", "TEXT"),
            ("sso_groups", "TEXT"),
        ]
        for col, col_type in sso_columns:
            try:
                cursor.execute(f"SELECT {col} FROM users LIMIT 1")
            except sqlite3.OperationalError:
                logger.info(f"Adding {col} column to users table for SSO")
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                conn.commit()

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating SSO tables: {e}", exc_info=True)


def _create_saml_tables():
    """
    Create SAML 2.0 provider configuration table and group-sync audit log.
    Safe to call multiple times (uses CREATE TABLE IF NOT EXISTS).
    """
    import sqlite3
    from pathlib import Path

    try:
        db_path = Path(__file__).resolve().parents[3] / "tda_auth.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        schema_path = Path(__file__).resolve().parents[3] / "schema" / "31_saml.sql"
        if schema_path.exists():
            cursor.executescript(schema_path.read_text())
            logger.debug("Applied schema: 31_saml.sql")
        else:
            # Inline fallback
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS saml_configurations (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    sp_entity_id TEXT NOT NULL, sp_acs_url TEXT,
                    sp_private_key TEXT, sp_certificate TEXT,
                    idp_entity_id TEXT NOT NULL, idp_sso_url TEXT NOT NULL,
                    idp_slo_url TEXT, idp_certificate TEXT NOT NULL,
                    email_attr TEXT DEFAULT 'email', name_attr TEXT DEFAULT 'displayName',
                    groups_attr TEXT, default_tier TEXT DEFAULT 'user',
                    group_tier_map TEXT, auto_provision_users INTEGER DEFAULT 1,
                    enabled INTEGER DEFAULT 1, button_label TEXT, icon_url TEXT,
                    display_order INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sso_sync_events (
                    id TEXT PRIMARY KEY, user_uuid TEXT NOT NULL,
                    config_id TEXT, config_type TEXT, sync_type TEXT NOT NULL,
                    old_tier TEXT, new_tier TEXT, old_groups TEXT, new_groups TEXT,
                    changed INTEGER DEFAULT 0,
                    synced_at TEXT DEFAULT (datetime('now'))
                );
            """)

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error creating SAML tables: {e}", exc_info=True)


def _run_user_table_migrations():
    """
    Run schema migrations for the users table.
    Adds new columns that were added after initial release.
    Safe to call multiple times (checks if columns exist).
    """
    import sqlite3

    try:
        db_path = DEFAULT_DB_PATH
        if not db_path.exists():
            return  # Database doesn't exist yet

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Migration: Add last_failed_login_at column for progressive delay
        try:
            cursor.execute("SELECT last_failed_login_at FROM users LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            logger.info("Adding last_failed_login_at column to users table for progressive delay")
            cursor.execute("ALTER TABLE users ADD COLUMN last_failed_login_at TIMESTAMP")
            conn.commit()

        # Migration: Add marketplace_visible column for marketplace opt-in
        try:
            cursor.execute("SELECT marketplace_visible FROM users LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding marketplace_visible column to users table for marketplace listing")
            cursor.execute("ALTER TABLE users ADD COLUMN marketplace_visible BOOLEAN NOT NULL DEFAULT 1")
            conn.commit()

        conn.close()

    except Exception as e:
        logger.error(f"Error running user table migrations: {e}", exc_info=True)


def _run_cost_table_migrations():
    """
    Run schema migrations for the llm_model_costs table.
    Adds columns introduced after initial release.
    """
    import sqlite3

    try:
        db_path = DEFAULT_DB_PATH
        if not db_path.exists():
            return

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Migration: Add is_deprecated column
        try:
            cursor.execute("SELECT is_deprecated FROM llm_model_costs LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding is_deprecated column to llm_model_costs table")
            cursor.execute("ALTER TABLE llm_model_costs ADD COLUMN is_deprecated BOOLEAN NOT NULL DEFAULT 0")
            conn.commit()

        conn.close()

    except Exception as e:
        logger.error(f"Error running cost table migrations: {e}", exc_info=True)


def _run_consumption_table_migrations():
    """
    Run schema migrations for the user_consumption table.
    Adds daily token tracking columns introduced in March 2026.
    Safe to call multiple times (checks if columns exist).
    """
    import sqlite3

    try:
        db_path = DEFAULT_DB_PATH
        if not db_path.exists():
            return

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Migration: Add daily token tracking columns
        try:
            cursor.execute("SELECT input_tokens_today FROM user_consumption LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding daily token tracking columns to user_consumption table")
            cursor.execute("ALTER TABLE user_consumption ADD COLUMN input_tokens_today INTEGER NOT NULL DEFAULT 0")
            cursor.execute("ALTER TABLE user_consumption ADD COLUMN output_tokens_today INTEGER NOT NULL DEFAULT 0")
            cursor.execute("ALTER TABLE user_consumption ADD COLUMN tokens_today INTEGER NOT NULL DEFAULT 0")
            conn.commit()

        conn.close()

    except Exception as e:
        logger.error(f"Error running consumption table migrations: {e}", exc_info=True)


def _run_knowledge_cdc_migrations():
    """
    Add CDC fields to knowledge_documents and collections tables.
    Safe to call multiple times — checks column existence before altering.

    knowledge_documents:
        source_uri       — where the document was fetched from (NULL = manual upload)
        ingest_epoch     — Unix timestamp of last successful write; generation cleanup key
        sync_enabled     — 1 = scheduler re-checks source_uri on each sync run
        last_checked_at  — ISO8601 UTC of last hash-check (manual or scheduled)

    collections:
        sync_interval         — scheduler cadence: 'hourly','6h','daily','weekly'
        embedding_model_locked — 1 after a validated re-index; 0 = consistency unverified
    """
    import sqlite3

    try:
        db_path = DEFAULT_DB_PATH
        if not db_path.exists():
            return

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # knowledge_documents: source_uri
        try:
            cursor.execute("SELECT source_uri FROM knowledge_documents LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("CDC: adding source_uri to knowledge_documents")
            cursor.execute("ALTER TABLE knowledge_documents ADD COLUMN source_uri TEXT")
            conn.commit()

        # knowledge_documents: ingest_epoch
        try:
            cursor.execute("SELECT ingest_epoch FROM knowledge_documents LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("CDC: adding ingest_epoch to knowledge_documents")
            cursor.execute("ALTER TABLE knowledge_documents ADD COLUMN ingest_epoch INTEGER")
            # Backfill from created_at so existing docs have a valid epoch
            cursor.execute("""
                UPDATE knowledge_documents
                SET ingest_epoch = CAST(strftime('%s', created_at) AS INTEGER)
                WHERE ingest_epoch IS NULL AND created_at IS NOT NULL
            """)
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"CDC: backfilled ingest_epoch for {cursor.rowcount} existing documents")

        # knowledge_documents: sync_enabled
        try:
            cursor.execute("SELECT sync_enabled FROM knowledge_documents LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("CDC: adding sync_enabled to knowledge_documents")
            cursor.execute("ALTER TABLE knowledge_documents ADD COLUMN sync_enabled INTEGER DEFAULT 0")
            conn.commit()

        # knowledge_documents: last_checked_at
        try:
            cursor.execute("SELECT last_checked_at FROM knowledge_documents LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("CDC: adding last_checked_at to knowledge_documents")
            cursor.execute("ALTER TABLE knowledge_documents ADD COLUMN last_checked_at TEXT")
            conn.commit()

        # knowledge_documents: chunk_count (per-document; summed by sync_collection_counts)
        try:
            cursor.execute("SELECT chunk_count FROM knowledge_documents LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("CDC: adding chunk_count to knowledge_documents")
            cursor.execute("ALTER TABLE knowledge_documents ADD COLUMN chunk_count INTEGER DEFAULT 0")
            conn.commit()

        # collections: sync_interval
        try:
            cursor.execute("SELECT sync_interval FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("CDC: adding sync_interval to collections")
            cursor.execute("ALTER TABLE collections ADD COLUMN sync_interval TEXT DEFAULT 'daily'")
            conn.commit()

        # collections: embedding_model_locked
        try:
            cursor.execute("SELECT embedding_model_locked FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("CDC: adding embedding_model_locked to collections")
            cursor.execute("ALTER TABLE collections ADD COLUMN embedding_model_locked INTEGER DEFAULT 0")
            conn.commit()

        # collections: source_root (base directory for resolving relative file:// URIs)
        try:
            cursor.execute("SELECT source_root FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("CDC: adding source_root to collections")
            cursor.execute("ALTER TABLE collections ADD COLUMN source_root TEXT DEFAULT NULL")
            conn.commit()

        # collections: next_sync_at (explicit schedule anchor; auto-advances by interval after each sync)
        try:
            cursor.execute("SELECT next_sync_at FROM collections LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("CDC: adding next_sync_at to collections")
            cursor.execute("ALTER TABLE collections ADD COLUMN next_sync_at TEXT DEFAULT NULL")
            conn.commit()

        # Staleness sweep index
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_docs_sync
            ON knowledge_documents (collection_id, sync_enabled, last_checked_at)
        """)

        # Upsert lookup index (get_document_by_filename)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_docs_filename
            ON knowledge_documents (collection_id, filename)
        """)

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error running knowledge CDC migrations: {e}", exc_info=True)
        try:
            conn.close()
        except Exception:
            pass


def _create_default_admin_if_needed():
    """
    Create default admin account (admin/admin) if no users exist in the database.
    This runs only once on first database initialization.
    """
    from trusted_data_agent.auth.models import User
    from trusted_data_agent.auth.security import hash_password
    
    try:
        with get_db_session() as session:
            # Check if any users exist
            user_count = session.query(User).count()
            
            if user_count == 0:
                # Create default admin account
                admin_user = User(
                    username='admin',
                    email='admin@example.com',
                    password_hash=hash_password('admin'),
                    is_admin=True,
                    is_active=True,
                    profile_tier='admin',
                    full_name='System Administrator'
                )
                session.add(admin_user)
                session.commit()
                
                logger.warning(
                    "⚠️  Default admin account created: username='admin', password='admin' "
                    "⚠️  CHANGE THIS PASSWORD IMMEDIATELY after first login!"
                )
            else:
                pass  # Database already initialized
                
    except Exception as e:
        logger.error(f"Error checking/creating default admin account: {e}", exc_info=True)


def _initialize_default_system_settings():
    """
    Initialize default system settings if they don't exist.
    This includes rate limiting configuration.
    """
    from trusted_data_agent.auth.models import SystemSettings
    import json
    from pathlib import Path
    
    # Load rate_limit_enabled default from config
    rate_limit_default = 'true'  # Fallback default
    try:
        config_path = Path(__file__).parent.parent.parent / 'tda_config.json'
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)
                rate_limit_config = config.get('rate_limit_enabled', 'on')
                # Convert 'on'/'off' to 'true'/'false'
                rate_limit_default = 'true' if rate_limit_config.lower() in ('on', 'true', '1', 'yes') else 'false'
    except Exception as e:
        logger.warning(f"Could not load rate_limit_enabled from config, using default: {e}")
    
    # Default rate limiting settings (configurable via tda_config.json)
    default_settings = {
        'rate_limit_enabled': (rate_limit_default, 'Enable or disable rate limiting system-wide'),
        'rate_limit_global_override': ('false', 'Override all consumption profiles with global limits'),
        'rate_limit_user_prompts_per_hour': ('100', 'Maximum prompts per hour for authenticated users'),
        'rate_limit_user_prompts_per_day': ('1000', 'Maximum prompts per day for authenticated users'),
        'rate_limit_user_configs_per_hour': ('10', 'Maximum configuration changes per hour for authenticated users'),
        'rate_limit_ip_login_per_minute': ('5', 'Maximum login attempts per minute per IP address'),
        'rate_limit_ip_register_per_hour': ('3', 'Maximum registrations per hour per IP address'),
        'rate_limit_ip_api_per_minute': ('60', 'Maximum API calls per minute per IP address'),
        'tts_mode': ('disabled', 'TTS credential mode: disabled, global, or user'),
    }
    
    try:
        with get_db_session() as session:
            for key, (value, description) in default_settings.items():
                # Check if setting already exists
                existing = session.query(SystemSettings).filter_by(setting_key=key).first()
                if not existing:
                    setting = SystemSettings(
                        setting_key=key,
                        setting_value=value,
                        description=description
                    )
                    session.add(setting)
                    logger.debug(f"Initialized system setting: {key} = {value}")
            
            session.commit()
            pass  # System settings initialized
            
    except Exception as e:
        logger.error(f"Error initializing system settings: {e}", exc_info=True)


def _sync_tts_mode_to_config():
    """
    Read tts_mode from system_settings and sync APP_CONFIG.VOICE_CONVERSATION_ENABLED.
    Called at startup after system settings are initialized.
    """
    from trusted_data_agent.auth.models import SystemSettings
    from trusted_data_agent.core.config import APP_CONFIG

    try:
        with get_db_session() as session:
            setting = session.query(SystemSettings).filter_by(setting_key='tts_mode').first()
            if setting:
                tts_mode = setting.setting_value
                APP_CONFIG.VOICE_CONVERSATION_ENABLED = (tts_mode != 'disabled')
                logger.debug(f"TTS mode synced from database: {tts_mode} (voice_enabled={APP_CONFIG.VOICE_CONVERSATION_ENABLED})")
    except Exception as e:
        logger.warning(f"Could not sync TTS mode from database: {e}")


def _bootstrap_tts_from_env():
    """
    Bootstrap global TTS credentials from environment variables at startup.
    Delegates to tts_service.bootstrap_tts_from_env().
    """
    try:
        from trusted_data_agent.core.tts_service import bootstrap_tts_from_env
        bootstrap_tts_from_env()
    except Exception as e:
        logger.warning(f"Could not bootstrap TTS credentials from environment: {e}")


def _initialize_document_upload_configs():
    """
    Initialize default document upload configurations for all LLM providers.
    Sets up sensible defaults that can be overridden by admins.
    """
    from trusted_data_agent.auth.models import DocumentUploadConfig
    
    # Default configurations for all supported providers
    # use_native_upload=True, enabled=True by default
    # Admins can override these settings via the UI
    default_providers = [
        'Google',      # Native File API support
        'Anthropic',   # Native base64 upload support
        'Amazon',      # Bedrock with Claude models
        'OpenAI',      # Vision models only
        'Azure',       # Vision deployments only
        'Friendli',    # Text extraction fallback
        'Ollama',      # Text extraction fallback
        'OpenRouter'   # Text extraction fallback (model-dependent)
    ]
    
    try:
        with get_db_session() as session:
            for provider in default_providers:
                # Check if config already exists
                existing = session.query(DocumentUploadConfig).filter_by(provider=provider).first()
                if not existing:
                    config = DocumentUploadConfig(
                        provider=provider,
                        use_native_upload=True,
                        enabled=True,
                        max_file_size_mb=None,  # Use provider defaults from DocumentUploadConfig class
                        supported_formats_override=None,  # Use provider defaults
                        notes='Default configuration - auto-initialized'
                    )
                    session.add(config)
                    logger.debug(f"Initialized document upload config for provider: {provider}")
            
            session.commit()
            pass  # Document upload configs initialized
            
    except Exception as e:
        logger.error(f"Error initializing document upload configs: {e}", exc_info=True)


def drop_all_tables():
    """
    Drop all tables. USE WITH CAUTION - this is destructive!
    Only for development/testing.
    """
    if os.environ.get('TDA_ENV') == 'production':
        raise RuntimeError("Cannot drop tables in production environment")
    
    logger.warning("Dropping all authentication database tables")
    Base.metadata.drop_all(bind=engine)
    logger.info("All tables dropped")


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    
    Usage:
        with get_db_session() as session:
            user = session.query(User).first()
    
    Automatically commits on success, rolls back on error.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {e}", exc_info=True)
        raise
    finally:
        session.close()


def get_db():
    """
    Dependency injection function for FastAPI/Quart.
    Returns a database session that auto-closes.
    
    Usage in routes:
        db = next(get_db())
        try:
            # use db
        finally:
            db.close()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _bootstrap_consumption_profiles():
    """
    Bootstrap consumption profiles from tda_config.json if they don't exist.
    """
    try:
        import json
        from pathlib import Path
        from trusted_data_agent.auth.models import ConsumptionProfile
        
        # Load tda_config.json
        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        if not config_path.exists():
            logger.warning("tda_config.json not found, skipping consumption profiles bootstrap")
            return
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        profiles_config = config.get('consumption_profiles', [])
        if not profiles_config:
            logger.info("No consumption profiles defined in tda_config.json")
            return
        
        default_profile_name = config.get('default_consumption_profile', 'Unlimited')
        
        with get_db_session() as session:
            for profile_data in profiles_config:
                # Check if profile already exists
                existing = session.query(ConsumptionProfile).filter_by(
                    name=profile_data['name']
                ).first()
                
                if existing:
                    continue
                
                # Create new profile
                profile = ConsumptionProfile(
                    name=profile_data['name'],
                    description=profile_data.get('description', ''),
                    prompts_per_hour=profile_data.get('prompts_per_hour'),
                    prompts_per_day=profile_data.get('prompts_per_day'),
                    config_changes_per_hour=profile_data.get('config_changes_per_hour'),
                    input_tokens_per_month=profile_data.get('input_tokens_per_month'),
                    output_tokens_per_month=profile_data.get('output_tokens_per_month'),
                    is_default=(profile_data['name'] == default_profile_name),
                    is_active=profile_data.get('is_active', True)
                )
                session.add(profile)
                logger.info(f"Bootstrapped consumption profile: {profile_data['name']}")
            
            session.commit()
            pass  # Consumption profiles initialized
    
    except Exception as e:
        logger.error(f"Failed to bootstrap consumption profiles: {e}", exc_info=True)


def _bootstrap_prompt_system():
    """
    Bootstrap the prompt management system:
    1. Create prompt schema tables
    2. Migrate prompts from prompts.dat
    3. Sync global parameters from tda_config.json
    """
    import sqlite3
    from pathlib import Path
    
    try:
        db_path = Path(__file__).resolve().parents[3] / "tda_auth.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if prompt tables already exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='prompts'")
        if cursor.fetchone():
            logger.debug("Prompt system tables already exist, skipping bootstrap")
            conn.close()
            return
        
        logger.info("Bootstrapping prompt management system...")
        
        # 1. Create schema from SQL files
        schema_dir = Path(__file__).resolve().parents[3] / "schema"
        schema_files = [
            "01_core_tables.sql",
            "02_parameters.sql",
            "03_profile_integration.sql",
            "04_indexes.sql",
            "05_views.sql",
            "06_prompt_mappings.sql",
            "07_genie_profiles.sql",
            "08_genie_global_settings.sql"
        ]
        
        for schema_file in schema_files:
            schema_path = schema_dir / schema_file
            if schema_path.exists():
                with open(schema_path, 'r') as f:
                    sql = f.read()
                    cursor.executescript(sql)
                logger.info(f"Applied schema: {schema_file}")

        # 1b. Run schema migrations (for existing installations that need column additions)
        migrations_dir = schema_dir / "migrations"
        if migrations_dir.exists():
            migration_files = sorted(migrations_dir.glob("*.sql"))
            for migration_file in migration_files:
                try:
                    with open(migration_file, 'r') as f:
                        sql = f.read()
                        cursor.executescript(sql)
                    logger.info(f"Applied migration: {migration_file.name}")
                except Exception as migration_error:
                    # Migrations may fail if already applied (e.g., column already exists)
                    # This is expected and safe to ignore
                    logger.debug(f"Migration {migration_file.name} skipped (likely already applied): {migration_error}")

        # 2. Run migration data (creates skeleton with placeholder content)
        migration_sql = schema_dir / "migration_data.sql"
        if migration_sql.exists():
            with open(migration_sql, 'r') as f:
                sql = f.read()
                cursor.executescript(sql)
            logger.info("Applied migration data (prompt classes, parameters)")
        
        # 3. Load and encrypt default prompts from encrypted distribution file
        try:
            import json
            from trusted_data_agent.agent.prompt_encryption import (
                derive_bootstrap_key,
                derive_tier_key,
                decrypt_prompt,
                encrypt_prompt,
                re_encrypt_prompt
            )
            
            # Load encrypted default prompts
            default_prompts_path = schema_dir / "default_prompts.dat"
            
            if not default_prompts_path.exists():
                logger.warning(f"default_prompts.dat not found at {default_prompts_path}")
                logger.warning("Prompts will remain as [MIGRATE] placeholders")
            else:
                # Derive bootstrap decryption key
                bootstrap_key = derive_bootstrap_key()
                
                # Use the actual license tier from the running application
                # This ensures prompts are encrypted with the correct tier key
                from trusted_data_agent.core.config import APP_STATE
                from trusted_data_agent.core.utils import get_project_root
                license_info = APP_STATE.get('license_info', {})
                
                if not license_info:
                    logger.error("No license info in APP_STATE - cannot encrypt prompts")
                    raise RuntimeError("License information required for prompt encryption")
                
                # Read license.key to get signature
                import os
                license_path = os.path.join(get_project_root(), "tda_keys", "license.key")
                
                with open(license_path, 'r') as lf:
                    license_data = json.load(lf)
                    license_info['signature'] = license_data['signature']
                
                tier_key = derive_tier_key(license_info)
                
                logger.info(f"Encrypting prompts for tier: {license_info.get('tier')}")
                
                # Load encrypted prompts
                with open(default_prompts_path, 'r', encoding='utf-8') as f:
                    encrypted_prompts = json.load(f)
                
                logger.info(f"Loaded {len(encrypted_prompts)} encrypted prompts from default_prompts.dat")
                
                # Process each prompt
                cursor.execute("SELECT id, name FROM prompts ORDER BY id")
                prompts_in_db = cursor.fetchall()
                
                migrated_count = 0
                for prompt_id, prompt_name in prompts_in_db:
                    if prompt_name in encrypted_prompts:
                        try:
                            encrypted_bootstrap_content = encrypted_prompts[prompt_name]

                            # Decrypt from bootstrap encryption
                            decrypted_content = decrypt_prompt(encrypted_bootstrap_content, bootstrap_key)

                            # Re-encrypt with tier key for database storage
                            tier_encrypted_content = encrypt_prompt(decrypted_content, tier_key)
                            
                            # Update database
                            cursor.execute(
                                "UPDATE prompts SET content = ? WHERE id = ?",
                                (tier_encrypted_content, prompt_id)
                            )
                            
                            migrated_count += 1
                            logger.debug(f"Encrypted and stored: {prompt_name}")
                        except Exception as e:
                            logger.error(f"Failed to migrate prompt {prompt_name}: {e}", exc_info=True)
                
                logger.info(f"✅ Migrated and encrypted {migrated_count} prompts to database")
                
                # Create version 1 entries in prompt_versions for all prompts
                logger.info("Creating version 1 entries in prompt_versions...")
                cursor.execute("SELECT id, name, content FROM prompts ORDER BY id")
                all_prompts = cursor.fetchall()
                
                for prompt_id, prompt_name, prompt_content in all_prompts:
                    cursor.execute("""
                        INSERT INTO prompt_versions (prompt_id, version, content, changed_by, change_reason, created_at)
                        VALUES (?, 1, ?, 'system', 'Base prompt', CURRENT_TIMESTAMP)
                    """, (prompt_id, prompt_content))
                
                logger.info(f"✅ Created version 1 entries for {len(all_prompts)} prompts")
        
        except ImportError as e:
            logger.error(f"Failed to import encryption utilities: {e}")
            logger.error("Prompts will remain as [MIGRATE] placeholders")
        except Exception as e:
            logger.error(f"Failed to load/encrypt default prompts: {e}", exc_info=True)
            logger.error("Prompts will remain as [MIGRATE] placeholders")
        
        # 4. Sync global parameters from tda_config.json
        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        if config_path.exists():
            import json
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            global_params = config.get('global_parameters', {})
            for param_name, param_value in global_params.items():
                cursor.execute(
                    "SELECT parameter_name FROM global_parameters WHERE parameter_name = ?",
                    (param_name,)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        """INSERT INTO global_parameters 
                           (parameter_name, display_name, parameter_type, description, default_value, is_system_managed, is_user_configurable)
                           VALUES (?, ?, 'string', 'Bootstrapped from tda_config.json', ?, 0, 1)""",
                        (param_name, param_name.replace('_', ' ').title(), str(param_value))
                    )
                    logger.info(f"Bootstrapped global parameter: {param_name} = {param_value}")
        
        # 5. Bootstrap default prompt mappings for system profile
        # These provide the baseline mappings that all profiles inherit by default
        default_mappings = config.get('default_prompt_mappings', {})
        if default_mappings:
            logger.info("Bootstrapping default prompt mappings...")
            mappings_created = 0
            
            # Master system prompts (provider-specific)
            for provider, prompt_name in default_mappings.get('master_system_prompts', {}).items():
                cursor.execute("""
                    INSERT OR IGNORE INTO profile_prompt_mappings 
                    (profile_id, category, subcategory, prompt_name, created_by)
                    VALUES ('__system_default__', 'master_system', ?, ?, 'system')
                """, (provider, prompt_name))
                if cursor.rowcount > 0:
                    mappings_created += 1
            
            # Workflow & Classification prompts
            for subcategory, prompt_name in default_mappings.get('workflow_classification', {}).items():
                cursor.execute("""
                    INSERT OR IGNORE INTO profile_prompt_mappings 
                    (profile_id, category, subcategory, prompt_name, created_by)
                    VALUES ('__system_default__', 'workflow_classification', ?, ?, 'system')
                """, (subcategory, prompt_name))
                if cursor.rowcount > 0:
                    mappings_created += 1
            
            # Error Recovery prompts
            for subcategory, prompt_name in default_mappings.get('error_recovery', {}).items():
                cursor.execute("""
                    INSERT OR IGNORE INTO profile_prompt_mappings 
                    (profile_id, category, subcategory, prompt_name, created_by)
                    VALUES ('__system_default__', 'error_recovery', ?, ?, 'system')
                """, (subcategory, prompt_name))
                if cursor.rowcount > 0:
                    mappings_created += 1
            
            # Data Operations prompts
            for subcategory, prompt_name in default_mappings.get('data_operations', {}).items():
                cursor.execute("""
                    INSERT OR IGNORE INTO profile_prompt_mappings 
                    (profile_id, category, subcategory, prompt_name, created_by)
                    VALUES ('__system_default__', 'data_operations', ?, ?, 'system')
                """, (subcategory, prompt_name))
                if cursor.rowcount > 0:
                    mappings_created += 1
            
            # Visualization prompts
            for subcategory, prompt_name in default_mappings.get('visualization', {}).items():
                cursor.execute("""
                    INSERT OR IGNORE INTO profile_prompt_mappings 
                    (profile_id, category, subcategory, prompt_name, created_by)
                    VALUES ('__system_default__', 'visualization', ?, ?, 'system')
                """, (subcategory, prompt_name))
                if cursor.rowcount > 0:
                    mappings_created += 1
            
            logger.info(f"✅ Bootstrapped {mappings_created} default prompt mappings")
        
        conn.commit()
        conn.close()
        
        logger.info("✅ Prompt management system bootstrapped successfully")
        
    except Exception as e:
        logger.error(f"Failed to bootstrap prompt system: {e}", exc_info=True)


def _sync_default_prompt_mappings():
    """
    Sync __system_default__ prompt mappings from tda_config.json on every startup.

    _bootstrap_prompt_system() only runs on first install (tables-exist guard).
    This function runs unconditionally so new providers added to tda_config.json
    (e.g. OpenRouter) get their __system_default__ DB row without a full DB reset.
    Uses INSERT OR IGNORE — safe to run repeatedly.
    """
    import sqlite3
    import json
    from pathlib import Path

    try:
        db_path = Path(__file__).resolve().parents[3] / "tda_auth.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Bail early if the table doesn't exist yet (bootstrap hasn't run)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='profile_prompt_mappings'")
        if not cursor.fetchone():
            conn.close()
            return

        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        with open(config_path, 'r') as f:
            config = json.load(f)

        default_mappings = config.get('default_prompt_mappings', {})
        if not default_mappings:
            conn.close()
            return

        synced = 0

        category_map = {
            'master_system_prompts': 'master_system',
            'workflow_classification': 'workflow_classification',
            'error_recovery': 'error_recovery',
            'data_operations': 'data_operations',
            'visualization': 'visualization',
        }

        for config_key, db_category in category_map.items():
            for subcategory, prompt_name in default_mappings.get(config_key, {}).items():
                cursor.execute("""
                    INSERT OR IGNORE INTO profile_prompt_mappings
                    (profile_id, category, subcategory, prompt_name, created_by)
                    VALUES ('__system_default__', ?, ?, ?, 'system')
                """, (db_category, subcategory, prompt_name))
                if cursor.rowcount > 0:
                    synced += 1
                    logger.info(f"Synced missing default mapping: {db_category}/{subcategory} -> {prompt_name}")

        conn.commit()
        conn.close()

        if synced:
            logger.info(f"✅ Synced {synced} new default prompt mappings from tda_config.json")

    except Exception as e:
        logger.error(f"Failed to sync default prompt mappings: {e}", exc_info=True)



def _bootstrap_recommended_models():
    """
    Bootstrap recommended models from tda_config.json if they don't exist.
    These models appear as "Recommended" in the model selection UI.
    """
    try:
        import json
        from pathlib import Path
        from trusted_data_agent.auth.models import RecommendedModel

        # Load tda_config.json
        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        if not config_path.exists():
            logger.warning("tda_config.json not found, skipping recommended models bootstrap")
            return

        with open(config_path, 'r') as f:
            config = json.load(f)

        models_config = config.get('recommended_models', [])
        if not models_config:
            logger.info("No recommended models defined in tda_config.json")
            return

        with get_db_session() as session:
            bootstrapped_count = 0
            for model_data in models_config:
                provider = model_data.get('provider')
                model_pattern = model_data.get('model_pattern')

                if not provider or not model_pattern:
                    logger.warning(f"Skipping invalid recommended model entry: {model_data}")
                    continue

                # Check if this provider/pattern combination already exists
                existing = session.query(RecommendedModel).filter_by(
                    provider=provider,
                    model_pattern=model_pattern
                ).first()

                if existing:
                    continue

                # Create new recommended model entry
                recommended = RecommendedModel(
                    provider=provider,
                    model_pattern=model_pattern,
                    notes=model_data.get('notes', ''),
                    is_active=True,
                    source='config_default'
                )
                session.add(recommended)
                bootstrapped_count += 1
                logger.info(f"Bootstrapped recommended model: {provider}/{model_pattern}")

            if bootstrapped_count > 0:
                session.commit()
                logger.info(f"✅ Bootstrapped {bootstrapped_count} recommended models")

    except Exception as e:
        logger.error(f"Failed to bootstrap recommended models: {e}", exc_info=True)


def _bootstrap_provider_models():
    """
    Bootstrap provider-available models from tda_config.json if they don't exist.

    Initially supports Friendli serverless models, but extensible to other providers
    that don't have dynamic model listing APIs.

    Models are stored with source='config_default' and can be managed via the
    maintenance/update_friendli_models.py script.
    """
    try:
        import json
        from pathlib import Path
        from trusted_data_agent.auth.models import ProviderAvailableModel

        # Load tda_config.json
        config_path = Path(__file__).resolve().parents[3] / "tda_config.json"
        if not config_path.exists():
            logger.warning("tda_config.json not found, skipping provider models bootstrap")
            return

        with open(config_path, 'r') as f:
            config = json.load(f)

        # Bootstrap Friendli serverless models
        friendli_models = config.get('friendli_serverless_models', [])
        if not friendli_models:
            logger.info("No friendli_serverless_models defined in tda_config.json")
            return

        with get_db_session() as session:
            bootstrapped_count = 0
            for model_data in friendli_models:
                model_id = model_data.get('model_id')

                if not model_id:
                    logger.warning(f"Skipping invalid model entry (no model_id): {model_data}")
                    continue

                # Check if this provider/model/endpoint_type combination already exists
                existing = session.query(ProviderAvailableModel).filter_by(
                    provider='Friendli',
                    model_id=model_id,
                    endpoint_type='serverless'
                ).first()

                if existing:
                    continue  # Skip if already exists (idempotent)

                # Create new model entry
                model = ProviderAvailableModel(
                    provider='Friendli',
                    model_id=model_id,
                    display_name=model_data.get('display_name'),
                    billing_type=model_data.get('billing_type', 'token'),
                    status=model_data.get('status', 'active'),
                    endpoint_type='serverless',
                    notes=model_data.get('notes', ''),
                    source='config_default',
                    is_active=True
                )
                session.add(model)
                bootstrapped_count += 1
                logger.info(f"Bootstrapped Friendli model: {model_id}")

            if bootstrapped_count > 0:
                session.commit()
                logger.info(f"✅ Bootstrapped {bootstrapped_count} Friendli serverless models")

    except Exception as e:
        logger.error(f"Failed to bootstrap provider models: {e}", exc_info=True)


# Database initialization is handled by the @app.before_serving startup hook in main.py.
# Do NOT call init_database() at module import time — it causes duplicate initialization.
