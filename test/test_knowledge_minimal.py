"""
Minimal Knowledge Repository Test - Create and inspect without cleanup
"""

import requests
import json

BASE_URL = "http://127.0.0.1:5050"

# Login
print("Logging in...")
response = requests.post(
    f"{BASE_URL}/api/v1/auth/login",
    json={"username": "admin", "password": "admin"}
)
token = response.json()['token']
print(f"✓ Logged in, token: {token[:20]}...")

# Create Knowledge Repository
print("\nCreating Knowledge Repository...")
response = requests.post(
    f"{BASE_URL}/api/v1/rag/collections",
    headers={"Authorization": f"Bearer {token}"},
    json={
        "name": "Test Knowledge Repo",
        "description": "Test repository",
        "repository_type": "knowledge",
        "chunking_strategy": "semantic",
        "chunk_size": 1000,
        "chunk_overlap": 200
    }
)
print(f"Status: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2)}")

if response.status_code in [200, 201]:
    collection_id = response.json()['collection_id']
    print(f"\n✓ Created collection ID: {collection_id}")
    
    # Try to list documents
    print(f"\nListing documents in collection {collection_id}...")
    response = requests.get(
        f"{BASE_URL}/api/v1/knowledge/repositories/{collection_id}/documents",
        headers={"Authorization": f"Bearer {token}"}
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 500:
        print(f"Error response: {response.text[:500]}")
    else:
        print(f"Response: {json.dumps(response.json(), indent=2)}")
