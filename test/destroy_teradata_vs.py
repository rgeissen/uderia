#!/usr/bin/env python3
"""
Destroy a Teradata vector store using the SDK
"""
import sys
import os
import logging
import tempfile

sys.path.insert(0, '/Users/livin2rave/my_private_code/uderia/src')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def destroy_vector_store(vs_name):
    """Destroy a Teradata vector store"""
    try:
        from teradatagenai import VectorStore, set_auth_token
        from trusted_data_agent.auth import encryption
        import sqlite3
        import shutil

        logger.info(f"Destroying vector store: {vs_name}")

        # Get credentials
        db_path = '/Users/livin2rave/my_private_code/uderia/tda_auth.db'
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        user_id = cursor.fetchone()['id']

        cursor.execute("""
            SELECT provider FROM user_credentials
            WHERE user_id = ? AND provider LIKE 'vectorstore_vs-default-teradata'
        """, (user_id,))

        provider = cursor.fetchone()['provider']
        config_id = provider.split('_', 1)[1]
        credentials = encryption.decrypt_credentials(user_id, f"vectorstore_{config_id}")
        conn.close()

        # Set auth token
        base_url = "https://pmlakeprod.innovationlabs.teradata.com/api/accounts/0507f6df-05a3-4d0b-bea7-2879bd3d64e0"
        pat_token = credentials['pat_token']
        pem_key_name = credentials['pem_key_name']
        pem_content = credentials['pem_content']
        username = credentials['username']

        # Create PEM file
        tmpdir = tempfile.mkdtemp(prefix="tda_vs_")
        pem_file_path = os.path.join(tmpdir, f"{pem_key_name}.pem")
        with open(pem_file_path, 'w') as f:
            content = pem_content
            if not content.endswith("\n"):
                content += "\n"
            f.write(content)

        try:
            set_auth_token(
                base_url=base_url,
                pat_token=pat_token,
                pem_file=pem_file_path,
                username=username
            )
            logger.info("Authentication successful")

            # Initialize VectorStore instance
            vs = VectorStore(vs_name)

            # Destroy the vector store
            logger.info(f"Calling destroy() on {vs_name}...")
            vs.destroy()

            logger.info(f"✅ Vector store {vs_name} destroyed successfully")
            return True

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    except Exception as e:
        logger.error(f"❌ Failed to destroy vector store: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("Usage: python destroy_teradata_vs.py <vector_store_name>")
        logger.info("Example: python destroy_teradata_vs.py test_sdk_direct_d73441eb")
        sys.exit(1)

    vs_name = sys.argv[1]
    success = destroy_vector_store(vs_name)
    sys.exit(0 if success else 1)
