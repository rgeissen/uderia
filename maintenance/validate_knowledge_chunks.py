#!/usr/bin/env python3
"""
Validate that a knowledge collection has chunks in ChromaDB.
"""

import sys
import chromadb
from pathlib import Path

def validate_collection_chunks(collection_name: str):
    """Check if collection has chunks in ChromaDB."""
    
    # ChromaDB path
    chroma_path = Path(__file__).parent.parent / ".chromadb_rag_cache"
    
    if not chroma_path.exists():
        print(f"❌ ChromaDB directory not found: {chroma_path}")
        return False
    
    print(f"📊 ChromaDB path: {chroma_path}")
    print(f"🔍 Checking collection: {collection_name}")
    
    try:
        # Initialize ChromaDB client
        client = chromadb.PersistentClient(path=str(chroma_path))
        
        # Get the collection
        collection = client.get_collection(name=collection_name)
        
        # Get count
        count = collection.count()
        print(f"\n✅ Collection found!")
        print(f"   Total chunks: {count}")
        
        if count > 0:
            # Get a sample of chunks
            results = collection.get(limit=3, include=['documents', 'metadatas'])
            
            print(f"\n📄 Sample chunks (showing first 3 of {count}):")
            for i, (doc_id, document, metadata) in enumerate(zip(results['ids'], results['documents'], results['metadatas']), 1):
                print(f"\n   Chunk {i}:")
                print(f"   - ID: {doc_id}")
                print(f"   - Length: {len(document)} chars")
                print(f"   - Preview: {document[:200]}...")
                if metadata:
                    print(f"   - Metadata: {metadata}")
            
            return True
        else:
            print("\n⚠️  Collection exists but has NO chunks!")
            return False
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python maintenance/validate_knowledge_chunks.py <collection_name>")
        print("\nExample: python maintenance/validate_knowledge_chunks.py tda_rag_coll_2_da862c")
        sys.exit(1)
    
    collection_name = sys.argv[1]
    success = validate_collection_chunks(collection_name)
    
    if success:
        print("\n✅ Validation successful - collection is properly populated!")
    else:
        print("\n❌ Validation failed - collection is empty or has issues!")
        sys.exit(1)
