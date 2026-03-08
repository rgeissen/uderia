# Check the app logs for connection errors
tail -100 /app/logs/*.log | grep -i "mcp\|connection\|error" | tail -30

# Or if logs aren't available, check if the MCP client can actually connect
python -c "
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_mcp():
    try:
        # Test the actual MCP connection the way your app does it
        server_params = StdioServerParameters(
            command='python',
            args=['-m', 'mcp_server'],
            env=None
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print('MCP connection successful!')
    except Exception as e:
        print(f'MCP connection failed: {e}')

asyncio.run(test_mcp())
"#!/usr/bin/env python3
"""
Re-upload knowledge document to collection 2 with proper chunking.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import chromadb
from pathlib import Path

# Document content
doc_path = Path(__file__).parent.parent / "test" / "knowledge_test_document.md"
if not doc_path.exists():
    print(f"Error: Document not found at {doc_path}")
    sys.exit(1)

with open(doc_path, 'r') as f:
    content = f.read()

print(f"Document size: {len(content)} bytes")

# Simple chunking by paragraphs
paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
print(f"Chunked into {len(paragraphs)} paragraphs")

# Connect to ChromaDB
client = chromadb.PersistentClient(path='.chromadb_rag_cache')
try:
    coll = client.get_collection('tda_rag_coll_2_da862c')
    print(f"Collection found: {coll.name}")
    
    # Clear existing data
    existing_ids = coll.get()['ids']
    if existing_ids:
        print(f"Deleting {len(existing_ids)} existing documents...")
        coll.delete(ids=existing_ids)
    
    # Add chunks
    print(f"Adding {len(paragraphs)} chunks...")
    chunk_ids = [f"chunk_{i}_{doc_path.stem}" for i in range(len(paragraphs))]
    metadatas = [{
        "document_id": doc_path.stem,
        "collection_id": "2",
        "chunk_index": str(i),
        "repository_type": "knowledge",
        "filename": doc_path.name,
        "chunk_method": "paragraph"
    } for i in range(len(paragraphs))]
    
    coll.add(
        ids=chunk_ids,
        documents=paragraphs,
        metadatas=metadatas
    )
    
    print(f"✅ Successfully added {coll.count()} chunks to collection")
    
    # Test query
    results = coll.query(
        query_texts=["What parallel degree for TerraData Schema Transfer Utility"],
        n_results=3
    )
    print(f"\nTest query returned {len(results['ids'][0])} results:")
    for i, (doc_id, dist) in enumerate(zip(results['ids'][0], results['distances'][0])):
        similarity = 1 - dist
        print(f"  {i+1}. {doc_id[:40]}... (similarity: {similarity:.3f})")
        if similarity > 0.7:
            print(f"      ✅ Above threshold (0.7)")
        else:
            print(f"      ⚠️ Below threshold (0.7)")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
