#!/usr/bin/env python3
"""
Test Uderia platform Teradata upload via REST API
Direct comparison to SDK test
"""
import sys
import os
import time
import requests
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:5050"
PDF_PATH = "/Users/livin2rave/my_private_code/uderia/repository_sources/Teradata_Data_Dictionary_17.00.pdf"

def test_uderia_upload():
    """Test Uderia platform upload via REST API"""

    # Step 1: Authenticate
    logger.info("Step 1: Authenticating...")
    auth_response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": "admin", "password": "admin"}
    )

    if auth_response.status_code != 200:
        logger.error(f"Authentication failed: {auth_response.status_code}")
        logger.error(auth_response.text)
        return False

    token = auth_response.json()["token"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    logger.info("✅ Authentication successful")

    # Step 2: Get vector store config ID
    logger.info("Step 2: Getting vector store configuration...")
    config_response = requests.get(
        f"{BASE_URL}/api/v1/vectorstore/configurations",
        headers=headers
    )

    if config_response.status_code != 200:
        logger.error(f"Failed to get configs: {config_response.status_code}")
        return False

    configs = config_response.json().get("configurations", [])
    teradata_config = None
    for config in configs:
        if config.get("name") == "Teradata Vector Store - CSA":
            teradata_config = config
            break

    if not teradata_config:
        logger.error("Teradata Vector Store - CSA not found")
        logger.info(f"Available configs: {[c.get('name') for c in configs]}")
        return False

    vector_store_config_id = teradata_config["id"]
    logger.info(f"✅ Found config ID: {vector_store_config_id}")

    # Step 3: Create knowledge repository (RAG collection)
    logger.info("Step 3: Creating knowledge repository...")
    repo_response = requests.post(
        f"{BASE_URL}/api/v1/rag/collections",
        headers=headers,
        json={
            "name": "test-uderia-teradata-upload",
            "description": "Test upload via Uderia REST API",
            "repository_type": "knowledge",
            "backend_type": "teradata",
            "vector_store_config_id": vector_store_config_id
        }
    )

    if repo_response.status_code not in [200, 201]:
        logger.error(f"Failed to create repository: {repo_response.status_code}")
        logger.error(repo_response.text)
        return False

    response_data = repo_response.json()

    if response_data.get("status") != "success":
        logger.error(f"Failed to create repository: {response_data.get('message')}")
        logger.error(f"Full response: {response_data}")
        return False

    collection_id = response_data.get("collection_id")
    if not collection_id:
        logger.error(f"No collection_id in response. Full response: {response_data}")
        return False

    logger.info(f"✅ Created repository ID: {collection_id}")

    # Step 4: Upload PDF
    logger.info(f"Step 4: Uploading PDF: {PDF_PATH}")

    if not os.path.exists(PDF_PATH):
        logger.error(f"PDF file not found: {PDF_PATH}")
        return False

    file_size_mb = os.path.getsize(PDF_PATH) / (1024 * 1024)
    logger.info(f"File size: {file_size_mb:.2f} MB")

    # Upload file with server-side chunking
    upload_headers = {"Authorization": f"Bearer {token}"}  # No Content-Type for multipart

    with open(PDF_PATH, 'rb') as f:
        files = {'file': ('Teradata_Data_Dictionary_17.00.pdf', f, 'application/pdf')}
        data = {
            'chunking_strategy': 'server_side',
            'chunk_size': '500',
            'optimized_chunking': 'true'
        }
        upload_response = requests.post(
            f"{BASE_URL}/api/v1/knowledge/repositories/{collection_id}/documents",
            headers=upload_headers,
            files=files,
            data=data
        )

    if upload_response.status_code != 200:
        logger.error(f"Upload failed: {upload_response.status_code}")
        logger.error(upload_response.text)

        # Check if repository was auto-deleted (atomic creation)
        check_response = requests.get(
            f"{BASE_URL}/api/v1/rag/collections",
            headers=headers
        )

        if check_response.status_code == 200:
            collections = check_response.json().get("collections", [])
            if not any(c["id"] == collection_id for c in collections):
                logger.info("✅ Atomic cleanup: Repository was automatically deleted")

        return False

    logger.info("✅ Upload initiated successfully")

    # Step 5: Poll for status
    logger.info("Step 5: Polling for status (max 10 minutes)...")
    start_time = time.time()
    max_wait = 600  # 10 minutes
    poll_interval = 5

    while (time.time() - start_time) < max_wait:
        status_response = requests.get(
            f"{BASE_URL}/api/v1/rag/collections/{collection_id}",
            headers=headers
        )

        if status_response.status_code != 200:
            logger.warning(f"Status check failed: {status_response.status_code}")
            time.sleep(poll_interval)
            continue

        collection_data = status_response.json().get("collection")
        vs_status = collection_data.get("vs_status", "UNKNOWN")
        doc_count = collection_data.get("document_count", 0)

        elapsed = int(time.time() - start_time)
        logger.info(f"[{elapsed}s] Status: {vs_status}, Documents: {doc_count}")

        if vs_status == "READY":
            logger.info(f"✅ SUCCESS! Vector store reached READY in {elapsed} seconds")
            logger.info(f"Documents: {doc_count}")
            return True

        elif vs_status == "CREATE FAILED":
            logger.error(f"❌ FAILED! Vector store creation failed")
            error_msg = collection_data.get("vs_error_message", "No error message")
            logger.error(f"Error: {error_msg}")
            return False

        time.sleep(poll_interval)

    logger.error(f"❌ TIMEOUT! Status did not reach READY after {max_wait} seconds")
    return False

if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("Testing Uderia Platform Teradata Upload via REST API")
    logger.info("=" * 80)

    success = test_uderia_upload()

    if success:
        logger.info("\n✅ TEST PASSED - Uderia platform upload successful")
        sys.exit(0)
    else:
        logger.error("\n❌ TEST FAILED - Uderia platform upload failed")
        sys.exit(1)
