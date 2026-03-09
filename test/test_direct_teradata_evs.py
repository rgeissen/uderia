#!/usr/bin/env python3
"""
Test direct Teradata EVS creation using teradatagenai SDK
Replicates the user's successful Jupyter notebook approach
"""
import sys
import os
import sqlite3
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, '/Users/livin2rave/my_private_code/uderia/src')

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_vector_store_credentials():
    """Retrieve and decrypt Teradata vector store credentials from database"""
    from trusted_data_agent.auth import encryption

    db_path = '/Users/livin2rave/my_private_code/uderia/tda_auth.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Find the admin user ID
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    admin_row = cursor.fetchone()
    if not admin_row:
        raise ValueError("Admin user not found")

    user_uuid = admin_row['id']
    logger.info(f"Found admin user ID: {user_uuid}")

    # Get vector store credentials
    # The credentials are stored with key pattern: vectorstore_{config_id}
    # Prioritize vs-default-teradata (CSA environment) over shared_demo
    cursor.execute("""
        SELECT id, provider, credentials_encrypted
        FROM user_credentials
        WHERE user_id = ? AND provider LIKE 'vectorstore%'
        ORDER BY
            CASE
                WHEN provider LIKE '%vs-default-teradata%' THEN 0
                ELSE 1
            END,
            created_at DESC
    """, (user_uuid,))

    creds_rows = cursor.fetchall()
    conn.close()

    if not creds_rows:
        raise ValueError("No vector store credentials found")

    logger.info(f"Found {len(creds_rows)} vector store credential entries")

    # Decrypt credentials and merge with backend_config
    for row in creds_rows:
        provider = row['provider']
        logger.info(f"Attempting to decrypt credentials for provider: {provider}")

        try:
            config_id = provider.split('_', 1)[1] if '_' in provider else None
            if config_id:
                decrypted = encryption.decrypt_credentials(user_uuid, f"vectorstore_{config_id}")
                if decrypted:
                    logger.info(f"Successfully decrypted credentials for config {config_id}")

                    # Load backend_config from preferences_json
                    import json
                    conn2 = sqlite3.connect(db_path)
                    conn2.row_factory = sqlite3.Row
                    cursor2 = conn2.cursor()
                    cursor2.execute("SELECT preferences_json FROM user_preferences WHERE user_id = ?", (user_uuid,))
                    prefs_row = cursor2.fetchone()
                    conn2.close()

                    if prefs_row:
                        prefs = json.loads(prefs_row['preferences_json'])
                        vs_configs = prefs.get('vector_store_configurations', [])
                        config = next((c for c in vs_configs if c.get('id') == config_id), None)
                        if config and 'backend_config' in config:
                            backend_config = config['backend_config']
                            logger.info(f"Merging backend_config: host={backend_config.get('host')}, database={backend_config.get('database')}")
                            decrypted.update(backend_config)

                    return decrypted, config_id
        except Exception as e:
            logger.error(f"Failed to decrypt {provider}: {e}")
            continue

    raise ValueError("Could not decrypt any vector store credentials")

def create_vector_store_with_sdk():
    """Create Teradata vector store using direct SDK calls"""
    try:
        from teradatagenai import VectorStore, set_auth_token
        logger.info("Successfully imported teradatagenai modules")
    except ImportError as e:
        logger.error(f"Failed to import teradatagenai: {e}")
        logger.error("Make sure teradatagenai is installed: pip install teradatagenai")
        return False

    # Get credentials
    try:
        credentials, config_id = get_vector_store_credentials()
        logger.info(f"Retrieved credentials for config: {config_id}")
        logger.info(f"Credential keys: {list(credentials.keys())}")
    except Exception as e:
        logger.error(f"Failed to get credentials: {e}")
        return False

    # Connection details (from command-line args or credentials)
    username = credentials.get('username', 'data_scientist')
    password = credentials.get('password', 'password')

    # Allow override via command-line arguments
    try:
        host = global_args.host if global_args.host else credentials.get('host', "td-clearscape-8bc32de8.env.clearscape.teradata.com")
        base_url = global_args.base_url if global_args.base_url else credentials.get('base_url', f"https://{host}/api")
        database = global_args.database if global_args.database else credentials.get('database', "DATA_SCIENTIST")
    except NameError:
        # global_args not defined (called directly without main)
        host = credentials.get('host', "td-clearscape-8bc32de8.env.clearscape.teradata.com")
        base_url = credentials.get('base_url', f"https://{host}/api")
        database = credentials.get('database', "DATA_SCIENTIST")

    # Teradata uses PAT token for authentication
    pat_token = credentials.get('api_key') or credentials.get('apiKey') or credentials.get('pat_token')
    pem_key_name = credentials.get('pem_key_name')
    pem_content = credentials.get('pem_content')

    if not pat_token:
        logger.error(f"No pat_token found in credentials. Available keys: {list(credentials.keys())}")
        return False

    logger.info(f"Connection details:")
    logger.info(f"  Host: {host}")
    logger.info(f"  Base URL: {base_url}")
    logger.info(f"  Database: {database}")
    logger.info(f"  Username: {username}")
    logger.info(f"  PAT Token: {pat_token[:20]}...")
    logger.info(f"  PEM Key Name: {pem_key_name}")

    # PDF file to upload
    pdf_path = "/Users/livin2rave/my_private_code/uderia/repository_sources/Teradata_Data_Dictionary_17.00.pdf"

    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        return False

    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    logger.info(f"PDF file: {pdf_path} ({file_size_mb:.2f} MB)")

    # Write PEM content to temporary file
    # CRITICAL: The SDK derives the JWT Key ID (kid) from the PEM *file name*.
    # The temp file MUST be named {key_name}.pem to match the key registered
    # in the VantageCloud Lake Console.
    import tempfile
    pem_file_path = None
    if pem_content and pem_key_name:
        tmpdir = tempfile.mkdtemp(prefix="tda_vs_")
        pem_file_path = os.path.join(tmpdir, f"{pem_key_name}.pem")
        with open(pem_file_path, 'w') as pem_file:
            content = pem_content
            if not content.endswith("\n"):
                content += "\n"
            pem_file.write(content)
        logger.info(f"Wrote PEM content to: {pem_file_path}")

    try:
        # Set GenAI authentication token (no database connection needed!)
        # VectorStore API works via REST, not SQL
        logger.info("Setting GenAI authentication token...")
        set_auth_token(
            base_url=base_url,
            pat_token=pat_token,
            pem_file=pem_file_path,
            username=username  # Required when create_context() not called
        )
        logger.info("GenAI authentication token set successfully")
    except Exception as e:
        logger.error(f"Failed to set auth token: {e}", exc_info=True)
        if pem_file_path and os.path.exists(pem_file_path):
            import shutil
            tmpdir = os.path.dirname(pem_file_path)
            shutil.rmtree(tmpdir, ignore_errors=True)
        return False

    # Create VectorStore instance (matches user's Jupyter approach)
    vs_name = f"test_sdk_direct_{os.urandom(4).hex()}"
    logger.info(f"Creating VectorStore: {vs_name}")

    try:
        # Initialize VectorStore with connection details
        vs = VectorStore(vs_name)
        logger.info("VectorStore instance created")

        # Create with document - server-side chunking approach
        logger.info("Calling vs.create() with document_files parameter...")
        logger.info("This will trigger server-side chunking by the EVS SDK")

        vs.create(
            embeddings_model='amazon.titan-embed-text-v1',
            search_algorithm='VECTORDISTANCE',
            object_names=['teradata_data_dict'],
            data_columns=['chunks'],
            vector_column='VectorIndex',
            chunk_size=500,
            optimized_chunking=False,
            overwrite_object=True,
            document_files=[pdf_path]
        )

        logger.info("✅ VectorStore creation completed successfully!")
        logger.info(f"VectorStore name: {vs_name}")

        # Get status
        try:
            status = vs.get_status()
            logger.info(f"VectorStore status: {status}")
        except Exception as e:
            logger.warning(f"Could not get status: {e}")

        # Cleanup PEM file and temp directory
        if pem_file_path and os.path.exists(pem_file_path):
            import shutil
            tmpdir = os.path.dirname(pem_file_path)
            shutil.rmtree(tmpdir, ignore_errors=True)
            logger.info(f"Cleaned up temporary PEM directory: {tmpdir}")

        return True

    except Exception as e:
        logger.error(f"❌ VectorStore creation failed: {e}", exc_info=True)

        # Cleanup PEM directory on error
        if pem_file_path and os.path.exists(pem_file_path):
            import shutil
            tmpdir = os.path.dirname(pem_file_path)
            shutil.rmtree(tmpdir, ignore_errors=True)

        return False

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Test direct Teradata EVS creation')
    parser.add_argument('--base-url', type=str,
                       help='Base URL for Teradata VantageCloud Lake (e.g., https://host/api/accounts/ENV_ID)')
    parser.add_argument('--host', type=str,
                       help='Teradata host for SQL connection (if needed)')
    parser.add_argument('--database', type=str, default='DATA_SCIENTIST',
                       help='Default database name (default: DATA_SCIENTIST)')

    args = parser.parse_args()

    # Store args globally for create_vector_store_with_sdk to access
    global_args = args

    logger.info("=" * 80)
    logger.info("Testing Direct Teradata EVS Creation (Jupyter Notebook Approach)")
    logger.info("=" * 80)

    # Pass arguments to the function
    success = create_vector_store_with_sdk()

    if success:
        logger.info("\n✅ Test PASSED - Direct SDK approach works")
        sys.exit(0)
    else:
        logger.error("\n❌ Test FAILED - Direct SDK approach failed")
        sys.exit(1)
