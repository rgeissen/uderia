"""
Backfill is_session_primer=True on KG-constructor-generated RAG cases.

The Knowledge Graph Constructor (_run_kg_agent_turn in rest_routes.py) submits
multi-turn agent executions with expanded internal prompts such as:

  Turn 1: "List every table in database '...' and describe each table's columns
           including column name, data type, nullability, and any constraints or
           keys. Present a complete structural inventory."

  Turn 2: "Based on the database structure discovered above, analyze '...' from
           a business perspective: ..."

Until the fix (is_session_primer=True added to _run_kg_agent_turn), these turns
were stored in ChromaDB as regular champion cases and surfaced in autocomplete.

This script finds all such cases across every collection and flips
is_session_primer to True so the /api/questions endpoint filters them out.

Usage:
    # Preview what would change (safe, no writes)
    python maintenance/backfill_kg_constructor_primer_flag.py

    # Apply the fix
    python maintenance/backfill_kg_constructor_primer_flag.py --execute
"""

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Known KG constructor query prefixes (case-sensitive, from rest_routes.py)
KG_PREFIXES = (
    "List every table in database '",
    "Based on the database structure discovered above, analyze '",
)

BATCH_SIZE = 5000  # ChromaDB safe batch limit


def is_kg_constructor_query(user_query: str) -> bool:
    return any(user_query.startswith(p) for p in KG_PREFIXES)


def process_collection(chroma_coll, dry_run: bool) -> dict:
    stats = {"total": 0, "already_flagged": 0, "to_update": 0, "updated": 0, "errors": 0}

    try:
        items = chroma_coll.get(include=["metadatas"])
    except Exception as e:
        print(f"    ERROR fetching items: {e}")
        stats["errors"] += 1
        return stats

    ids = items.get("ids", [])
    metas = items.get("metadatas", [])
    stats["total"] = len(ids)

    ids_to_fix = []
    metas_to_fix = []

    for doc_id, meta in zip(ids, metas):
        if meta.get("is_session_primer") is True:
            stats["already_flagged"] += 1
            continue

        user_query = meta.get("user_query", "")
        if not is_kg_constructor_query(user_query):
            continue

        fixed = dict(meta)
        fixed["is_session_primer"] = True
        ids_to_fix.append(doc_id)
        metas_to_fix.append(fixed)

        truncated = user_query[:80] + ("..." if len(user_query) > 80 else "")
        print(f"    {'[DRY-RUN] Would mark' if dry_run else 'Marking'}: {truncated!r}")

    stats["to_update"] = len(ids_to_fix)

    if not dry_run and ids_to_fix:
        for start in range(0, len(ids_to_fix), BATCH_SIZE):
            batch_ids = ids_to_fix[start:start + BATCH_SIZE]
            batch_metas = metas_to_fix[start:start + BATCH_SIZE]
            try:
                chroma_coll.update(ids=batch_ids, metadatas=batch_metas)
                stats["updated"] += len(batch_ids)
            except Exception as e:
                print(f"    ERROR in batch update: {e}")
                stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Backfill is_session_primer=True on KG constructor RAG cases"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes (default is dry-run)"
    )
    args = parser.parse_args()
    dry_run = not args.execute

    from trusted_data_agent.core.config import APP_CONFIG
    chroma_path = PROJECT_ROOT / APP_CONFIG.RAG_PERSIST_DIR
    if not chroma_path.exists():
        print(f"ERROR: ChromaDB directory not found at {chroma_path}")
        sys.exit(1)

    import chromadb
    client = chromadb.PersistentClient(path=str(chroma_path))

    collections = client.list_collections()
    print(f"{'DRY-RUN — no changes will be made' if dry_run else 'EXECUTE MODE — ChromaDB will be updated'}")
    print(f"Found {len(collections)} ChromaDB collection(s)\n")

    totals = {"total": 0, "already_flagged": 0, "to_update": 0, "updated": 0, "errors": 0}

    for coll_meta in collections:
        name = coll_meta.name if hasattr(coll_meta, "name") else str(coll_meta)
        coll = client.get_collection(name=name)
        count = coll.count()
        print(f"Collection '{name}' ({count} cases)")

        if count == 0:
            print("  Empty, skipping.\n")
            continue

        stats = process_collection(coll, dry_run)

        if stats["to_update"]:
            verb = "Would update" if dry_run else "Updated"
            print(f"  {verb} {stats['to_update']} KG-constructor case(s)")
        else:
            print(f"  No KG-constructor cases found (already_flagged={stats['already_flagged']})")

        for k in totals:
            totals[k] += stats[k]
        print()

    print("=" * 60)
    print(f"Total cases scanned : {totals['total']}")
    print(f"Already flagged     : {totals['already_flagged']}")
    print(f"KG cases found      : {totals['to_update']}")
    if not dry_run:
        print(f"Updated             : {totals['updated']}")
    print(f"Errors              : {totals['errors']}")
    print("=" * 60)

    if dry_run:
        print("\nDry-run complete. Run with --execute to apply changes.")
    else:
        print("\nDone.")


if __name__ == "__main__":
    main()
