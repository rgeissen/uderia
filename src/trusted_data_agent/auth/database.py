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

        # Create collections table (for marketplace)
        _create_collections_table()

        # Create template defaults table (for template configuration)
        _create_template_defaults_table()

        # Create global settings table (for three-tier configuration)
        _create_global_settings_table()

        # Create agent packs tables (for agent pack install/uninstall tracking)
        _create_agent_packs_tables()

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
        
        pass  # Collections table initialized
        
    except Exception as e:
        logger.error(f"Error creating collections table: {e}", exc_info=True)


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
            logger.info("Applied schema: 09_agent_packs.sql")
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
                logger.info(f"TTS mode synced from database: {tts_mode} (voice_enabled={APP_CONFIG.VOICE_CONVERSATION_ENABLED})")
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
        'Ollama'       # Text extraction fallback
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
            logger.info("Prompt system tables already exist, skipping bootstrap")
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
                            
                            # Handle dict prompts (like CHARTING_INSTRUCTIONS) specially
                            if isinstance(encrypted_bootstrap_content, dict):
                                logger.info(f"Processing dict prompt: {prompt_name}")
                                # Decrypt each value in the dict
                                decrypted_dict = {}
                                for key, encrypted_value in encrypted_bootstrap_content.items():
                                    if isinstance(encrypted_value, str):
                                        try:
                                            decrypted_dict[key] = decrypt_prompt(encrypted_value, bootstrap_key)
                                        except Exception as e:
                                            logger.warning(f"Failed to decrypt {prompt_name}[{key}]: {e}")
                                            decrypted_dict[key] = encrypted_value
                                    else:
                                        decrypted_dict[key] = encrypted_value
                                
                                # Re-encrypt the dict as JSON
                                decrypted_json = json.dumps(decrypted_dict)
                                tier_encrypted_content = encrypt_prompt(decrypted_json, tier_key)
                            else:
                                # Regular string prompt
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


# Initialize database on module import (authentication is always enabled)
init_database()
