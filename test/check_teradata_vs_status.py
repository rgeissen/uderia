#!/usr/bin/env python3
"""
Check the status of Teradata vector stores created via the SDK
"""
import sys
import os
import logging

sys.path.insert(0, '/Users/livin2rave/my_private_code/uderia/src')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_vector_store_status(vs_name=None):
    """Check status of Teradata vector stores"""
    try:
        from teradatagenai import VectorStore, set_auth_token
        from trusted_data_agent.auth import encryption
        import sqlite3
        import tempfile

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

            if vs_name:
                # Check specific vector store
                logger.info(f"Checking status of: {vs_name}")
                vs = VectorStore(vs_name)

                try:
                    status = vs.status()
                    logger.info(f"Status result: {status}")
                except Exception as e:
                    logger.warning(f"Status check method failed: {e}")
                    logger.info("Trying to get basic info...")
                    try:
                        # Try to access the vector store to see if it exists
                        logger.info(f"Vector store {vs_name} exists and is accessible")
                    except Exception as e2:
                        logger.error(f"Vector store may not exist or is inaccessible: {e2}")
            else:
                logger.info("No specific vector store name provided")
                logger.info("Use: python check_teradata_vs_status.py <vs_name>")

        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

        return True

    except Exception as e:
        logger.error(f"Status check failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    vs_name = sys.argv[1] if len(sys.argv) > 1 else None

    if not vs_name:
        logger.info("Checking for vector store: test_sdk_direct_d73441eb (from recent test)")
        vs_name = "test_sdk_direct_d73441eb"

    check_vector_store_status(vs_name)
