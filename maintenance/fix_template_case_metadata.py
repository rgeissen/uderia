"""
Backfill mcp_server_id on template-generated RAG cases.

The "One Default Collection per MCP Server" commit (fb891861, Jan 2026) added
an mcp_server_id filter to the planner retrieval path but never updated the
template generator to stamp mcp_server_id on cases it creates.  This means
every template-generated case has mcp_server_id=None in ChromaDB and is
silently filtered out during retrieval.

This script patches existing ChromaDB metadata for all planner collections
by setting mcp_server_id from the collection's own database record.

Usage:
    python maintenance/fix_template_case_metadata.py [--dry-run]
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def get_planner_collections(db_path: Path):
    """Get all planner collections with their mcp_server_id."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, collection_name, mcp_server_id
        FROM collections
        WHERE repository_type = 'planner' AND enabled = 1
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def main():
    parser = argparse.ArgumentParser(description="Backfill mcp_server_id on template RAG cases")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying data")
    args = parser.parse_args()

    db_path = PROJECT_ROOT / "tda_auth.db"
    chroma_path = PROJECT_ROOT / ".chromadb_rag_cache"

    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)
    if not chroma_path.exists():
        print(f"ERROR: ChromaDB directory not found at {chroma_path}")
        sys.exit(1)

    import chromadb
    client = chromadb.PersistentClient(path=str(chroma_path))

    collections = get_planner_collections(db_path)
    print(f"Found {len(collections)} planner collection(s)\n")

    total_updated = 0

    for coll_info in collections:
        coll_id = coll_info["id"]
        coll_name = coll_info["collection_name"]
        mcp_server_id = coll_info["mcp_server_id"] or ""

        if not mcp_server_id:
            print(f"  Collection {coll_id} ({coll_name}): no mcp_server_id in DB, skipping")
            continue

        try:
            chroma_coll = client.get_collection(name=coll_name)
        except Exception as e:
            print(f"  Collection {coll_id} ({coll_name}): not found in ChromaDB ({e}), skipping")
            continue

        count = chroma_coll.count()
        if count == 0:
            print(f"  Collection {coll_id} ({coll_name}): empty, skipping")
            continue

        # Fetch all items
        items = chroma_coll.get(include=["metadatas"])
        ids_to_fix = []
        metadatas_to_fix = []

        for doc_id, meta in zip(items["ids"], items["metadatas"]):
            current_mcp = meta.get("mcp_server_id")
            if current_mcp is None or current_mcp == "":
                fixed_meta = dict(meta)
                fixed_meta["mcp_server_id"] = mcp_server_id
                ids_to_fix.append(doc_id)
                metadatas_to_fix.append(fixed_meta)

        if not ids_to_fix:
            print(f"  Collection {coll_id} ({coll_name}): {count} cases, all have mcp_server_id set")
            continue

        print(f"  Collection {coll_id} ({coll_name}): {len(ids_to_fix)}/{count} cases need mcp_server_id='{mcp_server_id}'")

        if not args.dry_run:
            chroma_coll.update(ids=ids_to_fix, metadatas=metadatas_to_fix)
            print(f"    -> Updated {len(ids_to_fix)} cases")
            total_updated += len(ids_to_fix)
        else:
            print(f"    -> Would update {len(ids_to_fix)} cases (dry-run)")
            total_updated += len(ids_to_fix)

    print(f"\nDone. {'Would update' if args.dry_run else 'Updated'} {total_updated} case(s) total.")


if __name__ == "__main__":
    main()
