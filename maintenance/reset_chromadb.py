#!/usr/bin/env python3
"""
Reset ChromaDB by deleting the corrupted database and letting it rebuild from JSON case files.
This is safe because all RAG data is stored in JSON files - ChromaDB is just a vector index.
"""

import shutil
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent  # Go up from maintenance/ to project root
chromadb_dir = project_root / '.chromadb_rag_cache'

print("=" * 70)
print("ChromaDB Reset Utility")
print("=" * 70)
print()
print("This will delete the corrupted ChromaDB vector database.")
print("Don't worry - all your RAG case data is safe in JSON files!")
print("ChromaDB will rebuild the vector index from those files on next startup.")
print()

if chromadb_dir.exists():
    print(f"Found ChromaDB directory: {chromadb_dir}")
    print(f"Size: {sum(f.stat().st_size for f in chromadb_dir.rglob('*') if f.is_file()) / 1024:.1f} KB")
    print()
    
    response = input("Delete ChromaDB directory? (yes/no): ").strip().lower()
    
    if response == 'yes':
        try:
            shutil.rmtree(chromadb_dir)
            print("✓ ChromaDB directory deleted successfully!")
            print()
            print("Next steps:")
            print("1. Start your application normally")
            print("2. RAG system will rebuild the vector index from your JSON files")
            print("3. This may take a moment if you have many cases")
        except Exception as e:
            print(f"✗ Error deleting directory: {e}")
            print()
            print("Manual cleanup required:")
            print(f"  rm -rf {chromadb_dir}")
    else:
        print("Operation cancelled.")
else:
    print(f"ChromaDB directory not found at: {chromadb_dir}")
    print("Nothing to clean up - database will be created fresh on next startup.")

print()
print("=" * 70)
