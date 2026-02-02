#!/usr/bin/env python3
"""
Remove all VAT profiles and knowledge collections from Uderia.

Reads the mapping files produced by the import and profile creation scripts,
then deletes everything via the REST API (profiles) and direct database/ChromaDB
access (collections).

Usage:
    python agent_packs/vat/cleanup_vat.py [--base-url http://localhost:5050]

This is safe to run multiple times — it skips items that are already gone.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import chromadb
import requests


CHROMA_PERSIST_DIR = ".chromadb_rag_cache"
AUTH_DB = "tda_auth.db"


def get_jwt_token(base_url: str, username: str, password: str) -> str:
    """Authenticate and return JWT token."""
    resp = requests.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"ERROR: Login failed ({resp.status_code}): {resp.text}")
        sys.exit(1)
    return resp.json()["token"]


def delete_profile(base_url: str, token: str, profile_id: str, label: str) -> bool:
    """Delete a profile via REST API. Returns True on success."""
    resp = requests.delete(
        f"{base_url}/api/v1/profiles/{profile_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if resp.status_code == 200:
        print(f"    Deleted  {label} ({profile_id})")
        return True
    elif resp.status_code == 404:
        print(f"    Skipped  {label} (already removed)")
        return True
    else:
        print(f"    FAILED   {label}: HTTP {resp.status_code} — {resp.text[:200]}")
        return False


def delete_collection_from_db(db_conn: sqlite3.Connection, collection_id: int,
                               chroma_name: str, label: str) -> bool:
    """Delete a collection from the database and knowledge_documents table."""
    cursor = db_conn.cursor()

    cursor.execute("SELECT id FROM collections WHERE id = ?", (collection_id,))
    if not cursor.fetchone():
        print(f"    Skipped  {label} (id={collection_id}, not in DB)")
        return True

    cursor.execute("DELETE FROM knowledge_documents WHERE collection_id = ?", (collection_id,))
    doc_rows = cursor.rowcount
    cursor.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    db_conn.commit()

    print(f"    Deleted  {label} (id={collection_id}, {doc_rows} doc records)")
    return True


def delete_collection_from_chroma(chroma_client: chromadb.PersistentClient,
                                   chroma_name: str, label: str) -> bool:
    """Delete a ChromaDB collection by name."""
    try:
        chroma_client.delete_collection(name=chroma_name)
        print(f"    Deleted  ChromaDB: {chroma_name}")
        return True
    except ValueError:
        print(f"    Skipped  ChromaDB: {chroma_name} (not found)")
        return True
    except Exception as e:
        print(f"    FAILED   ChromaDB: {chroma_name} — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Remove all VAT profiles and collections from Uderia")
    parser.add_argument("--base-url", type=str, default="http://localhost:5050")
    parser.add_argument("--username", type=str, default="admin")
    parser.add_argument("--password", type=str, default="admin")
    parser.add_argument(
        "--import-dir", type=str,
        default=str(Path(__file__).parent / "import_output"),
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    import_dir = Path(args.import_dir)
    profile_mapping_path = import_dir / "profile_mapping.json"
    collection_mapping_path = import_dir / "collection_mapping.json"

    # Load mappings
    profile_mapping = {}
    collection_mapping = {}

    if profile_mapping_path.exists():
        with open(profile_mapping_path) as f:
            profile_mapping = json.load(f)
    else:
        print(f"WARNING: {profile_mapping_path} not found — no profiles to delete")

    if collection_mapping_path.exists():
        with open(collection_mapping_path) as f:
            collection_mapping = json.load(f)
    else:
        print(f"WARNING: {collection_mapping_path} not found — no collections to delete")

    if not profile_mapping and not collection_mapping:
        print("Nothing to clean up.")
        return

    # Show what will be removed
    sub_profiles = profile_mapping.get("sub_profiles", {})
    genie_id = profile_mapping.get("genie_profile_id")
    profile_count = len(sub_profiles) + (1 if genie_id else 0)
    collection_count = len(collection_mapping)

    print(f"\nThis will remove from Uderia:")
    print(f"  - {profile_count} profiles ({len(sub_profiles)} sub-profiles + Genie coordinator)")
    print(f"  - {collection_count} knowledge collections (DB records + ChromaDB data)")

    if not args.yes:
        answer = input("\nProceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    # Authenticate
    print(f"\nAuthenticating as '{args.username}'...")
    token = get_jwt_token(args.base_url, args.username, args.password)

    # --- Phase 1: Delete profiles (Genie first, then sub-profiles) ---
    print(f"\n{'='*60}")
    print("Deleting profiles")
    print(f"{'='*60}")

    profile_ok = 0
    profile_total = 0

    if genie_id:
        profile_total += 1
        if delete_profile(args.base_url, token, genie_id, "@VAT (Genie)"):
            profile_ok += 1

    for tag, pid in sub_profiles.items():
        profile_total += 1
        if delete_profile(args.base_url, token, pid, f"@{tag}"):
            profile_ok += 1

    # --- Phase 2: Delete collections (DB + ChromaDB) ---
    print(f"\n{'='*60}")
    print("Deleting knowledge collections")
    print(f"{'='*60}")

    db_conn = sqlite3.connect(AUTH_DB)
    chroma_dir = Path(CHROMA_PERSIST_DIR)
    chroma_client = chromadb.PersistentClient(path=str(chroma_dir)) if chroma_dir.exists() else None

    coll_ok = 0
    coll_total = 0

    for corpus, info in collection_mapping.items():
        if "error" in info:
            continue
        coll_total += 1
        collection_id = info["collection_id"]
        chroma_name = info.get("chroma_name", "")

        print(f"\n  {corpus}:")
        db_ok = delete_collection_from_db(db_conn, collection_id, chroma_name, corpus)

        chroma_ok = True
        if chroma_client and chroma_name:
            chroma_ok = delete_collection_from_chroma(chroma_client, chroma_name, corpus)

        if db_ok and chroma_ok:
            coll_ok += 1

    db_conn.close()

    # --- Summary ---
    print(f"\n{'='*60}")
    print("CLEANUP SUMMARY")
    print(f"{'='*60}")
    print(f"  Profiles deleted:    {profile_ok}/{profile_total}")
    print(f"  Collections deleted: {coll_ok}/{coll_total}")

    if profile_ok == profile_total and coll_ok == coll_total:
        print("\nAll VAT resources removed. You can now re-run the import pipeline.")
    else:
        print("\nSome items could not be removed — check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
