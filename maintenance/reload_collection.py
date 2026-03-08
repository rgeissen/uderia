#!/usr/bin/env python3
"""
Force reload a collection in the RAG retriever.
This is needed when documents are added directly to ChromaDB outside the normal flow.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from trusted_data_agent.core.config import APP_STATE, APP_CONFIG
from pathlib import Path

collection_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2

print(f"Reloading collection {collection_id}...")

# Get the RAG retriever instance
retriever = APP_STATE.get('rag_retriever_instance')
if not retriever:
    print("Error: RAG retriever not initialized. Is the server running?")
    sys.exit(1)

# Get collection metadata
collections = APP_STATE.get('rag_collections', [])
coll_meta = next((c for c in collections if c['id'] == collection_id), None)

if not coll_meta:
    print(f"Error: Collection {collection_id} not found in APP_STATE")
    sys.exit(1)

print(f"Found collection: {coll_meta['name']} ({coll_meta['collection_name']})")

# Remove from retriever
if collection_id in retriever.collections:
    del retriever.collections[collection_id]
    print(f"Removed old collection {collection_id} from retriever")

# Reload from ChromaDB
try:
    collection = retriever.client.get_collection(
        name=coll_meta['collection_name']
    )
    retriever.collections[collection_id] = collection
    count = collection.count()
    print(f"✅ Reloaded collection {collection_id}: {count} documents")
except Exception as e:
    print(f"❌ Error reloading collection: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
