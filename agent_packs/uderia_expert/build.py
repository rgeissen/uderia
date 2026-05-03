#!/usr/bin/env python3
"""
Build uderia_expert.agentpack from all Uderia platform documentation.

Phases:
  1. Scan  — walk docs/**/*.md + README.md
  2. Chunk — RecursiveCharacterTextSplitter(1000/200)
  3. Embed — SentenceTransformer("all-MiniLM-L6-v2")
  4. Pack  — collection ZIP (collection_metadata.json + documents.jsonl)
  5. Manifest — format_version 1.1, single rag_focused profile
  6. Bundle — uderia_expert.agentpack
  7. Import (--import) — POST to platform + PATCH source_uri/sync_enabled per doc

Usage:
    # Build only
    python agent_packs/uderia_expert/build.py

    # Build + auto-import + wire CDC sync
    UDERIA_USERNAME=admin UDERIA_PASSWORD=admin \\
      python agent_packs/uderia_expert/build.py --import

    # Force full rebuild (re-embeds everything)
    python agent_packs/uderia_expert/build.py --import --force

Prerequisites:
    pip install sentence-transformers langchain-text-splitters requests numpy

Output:
    agent_packs/uderia_expert/output/uderia_expert.agentpack
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

# ── Constants ─────────────────────────────────────────────────────────────────

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
BATCH_SIZE = 5000       # Chunks per JSONL batch (matches collection_utils.py)
EMBED_BATCH_SIZE = 64

PACK_NAME = "Uderia Expert"
PACK_DESCRIPTION = "RAG-powered assistant over all Uderia platform documentation. Ask anything about architecture, configuration, API, RAG templates, connectors, or the IFOC methodology."
PACK_AUTHOR = "Uderia"
PACK_VERSION = "1.0.0"

COLLECTION_REF  = "uderia_knowledge"
COLLECTION_NAME = "Uderia Documentation"

PROFILE_TAG  = "UDERIA"
PROFILE_NAME = "Uderia Expert"

# Canonical project root: two levels above this file (agent_packs/uderia_expert/build.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Document scanning ─────────────────────────────────────────────────────────

def collect_source_files(project_root: Path) -> list[dict]:
    """Return list of {abs_path, filename, category, rel_path} for all .md docs."""
    files = []

    # docs/**/*.md
    docs_root = project_root / "docs"
    if docs_root.exists():
        for md_path in sorted(docs_root.rglob("*.md")):
            parent_name = md_path.parent.name
            # Flatten nested categories to their immediate parent under docs/
            # e.g. docs/Architecture/sub/file.md → category = Architecture
            try:
                rel = md_path.relative_to(docs_root)
                category = rel.parts[0] if len(rel.parts) > 1 else "docs"
            except ValueError:
                category = "docs"

            files.append({
                "abs_path": str(md_path),
                "filename": md_path.name,
                "category": category,
                "rel_path": str(md_path.relative_to(project_root)),
            })

    # README.md at project root
    readme = project_root / "README.md"
    if readme.exists():
        files.append({
            "abs_path": str(readme),
            "filename": "README.md",
            "category": "root",
            "rel_path": "README.md",
        })

    return files


# ── Text utilities ─────────────────────────────────────────────────────────────

def extract_title(content: str, filename: str) -> str:
    """Extract first H1 heading from markdown, falling back to filename stem."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return Path(filename).stem.replace("_", " ").replace("-", " ")


# ── Core processing ───────────────────────────────────────────────────────────

def process_docs(source_files: list[dict], model: SentenceTransformer) -> tuple[bytes, dict]:
    """Chunk, embed, and pack all source files into a collection ZIP (in-memory bytes).

    Returns (zip_bytes, stats_dict).
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    all_ids: list[str] = []
    all_chunks: list[str] = []
    all_metadatas: list[dict] = []

    skipped = 0
    created_at = datetime.now(timezone.utc).isoformat()

    for doc_info in source_files:
        abs_path = doc_info["abs_path"]
        filename = doc_info["filename"]
        category = doc_info["category"]
        rel_path = doc_info["rel_path"]  # root-relative, e.g. docs/Architecture/foo.md

        try:
            content = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"  WARN: Cannot read {abs_path}: {e}")
            skipped += 1
            continue

        if not content.strip():
            skipped += 1
            continue

        title = extract_title(content, filename)
        chunks = splitter.split_text(content)
        if not chunks:
            skipped += 1
            continue

        # Stable document ID derived from abs_path (survives multiple builds)
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, abs_path))
        tags = f"uderia,{category}"

        for i, chunk_text in enumerate(chunks):
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:8]
            chunk_id = f"{doc_id}_chunk_{i}_{content_hash}"

            all_ids.append(chunk_id)
            all_chunks.append(chunk_text)
            all_metadatas.append({
                "document_id": doc_id,
                "filename": filename,
                "title": title,
                "category": category,
                "source_uri": f"file://{rel_path}",
                "chunk_index": i,
                "chunk_method": "recursive",
                "document_type": "markdown",
                "tags": tags,
                "source": "build",
                "created_at": created_at,
            })

    if not all_chunks:
        raise RuntimeError("No chunks generated — check that docs/ and README.md exist.")

    unique_docs = len({m["document_id"] for m in all_metadatas})
    print(f"  Documents : {len(source_files) - skipped} processed, {skipped} skipped")
    print(f"  Chunks    : {len(all_chunks)}")

    # ── Embed ──────────────────────────────────────────────────────────────────
    print(f"  Embedding : {EMBEDDING_MODEL} …")
    embeddings = model.encode(
        all_chunks,
        show_progress_bar=True,
        batch_size=EMBED_BATCH_SIZE,
        normalize_embeddings=False,
    )
    embeddings_list = embeddings.tolist()
    print(f"  Vectors   : {len(embeddings_list)} × {len(embeddings_list[0])}d")

    # ── Collection ZIP ─────────────────────────────────────────────────────────
    collection_metadata = {
        "export_version": "1.0",
        "name": COLLECTION_NAME,
        "description": PACK_DESCRIPTION,
        "repository_type": "knowledge",
        "embedding_model": EMBEDDING_MODEL,
        "chunking_strategy": "recursive",
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "document_count": unique_docs,
        "exported_at": created_at,
    }

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("collection_metadata.json", json.dumps(collection_metadata, indent=2))

        jsonl_lines = []
        total = len(all_ids)
        for start in range(0, total, BATCH_SIZE):
            end = min(start + BATCH_SIZE, total)
            batch = {
                "ids":        all_ids[start:end],
                "documents":  all_chunks[start:end],
                "metadatas":  all_metadatas[start:end],
                "embeddings": embeddings_list[start:end],
            }
            jsonl_lines.append(json.dumps(batch, allow_nan=False))
        zf.writestr("documents.jsonl", "\n".join(jsonl_lines) + "\n")

    zip_bytes = buf.getvalue()
    size_mb = len(zip_bytes) / (1024 * 1024)
    print(f"  Collection : {size_mb:.1f} MB ({len(jsonl_lines)} JSONL batch(es))")

    stats = {
        "documents": unique_docs,
        "chunks": len(all_chunks),
        "zip_size_mb": round(size_mb, 2),
    }
    return zip_bytes, stats


# ── Manifest ──────────────────────────────────────────────────────────────────

def build_manifest(stats: dict) -> dict:
    """Build manifest.json for format_version 1.1 (single rag_focused profile)."""
    return {
        "format_version": "1.1",
        "name": PACK_NAME,
        "description": PACK_DESCRIPTION,
        "author": PACK_AUTHOR,
        "version": PACK_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tags": ["uderia", "documentation", "platform", "rag"],
        "profiles": [
            {
                "tag": PROFILE_TAG,
                "name": PROFILE_NAME,
                "description": "Answers questions about the Uderia platform using the full documentation corpus.",
                "profile_type": "rag_focused",
                "role": "standalone",
                "collection_refs": [COLLECTION_REF],
                "classification_mode": "light",
                "knowledgeConfig": {
                    "maxDocs": 10,
                    "maxTokens": 8000,
                    "minRelevanceScore": 0.25,
                    "maxChunksPerDocument": 3,
                },
            }
        ],
        "collections": [
            {
                "ref": COLLECTION_REF,
                "name": COLLECTION_NAME,
                "repository_type": "knowledge",
                "description": PACK_DESCRIPTION,
                "file": f"collections/{COLLECTION_REF}.zip",
                "documents": stats.get("documents", 0),
                "chunks": stats.get("chunks", 0),
            }
        ],
    }


# ── Auto-import ───────────────────────────────────────────────────────────────

def _get_jwt(base_url: str, username: str, password: str) -> str:
    import requests
    resp = requests.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("token")
    if not token:
        raise RuntimeError(f"Login succeeded but no token in response: {resp.json()}")
    return token


def _import_pack(base_url: str, jwt: str, pack_path: Path) -> dict:
    import requests
    with open(pack_path, "rb") as fh:
        resp = requests.post(
            f"{base_url}/api/v1/agent-packs/import",
            headers={"Authorization": f"Bearer {jwt}"},
            files={"file": (pack_path.name, fh, "application/octet-stream")},
            data={"data": json.dumps({"conflict_strategy": "replace"})},
            timeout=300,
        )
    resp.raise_for_status()
    return resp.json()


def _find_collection_id(base_url: str, jwt: str, collection_name: str) -> int | None:
    import requests
    resp = requests.get(
        f"{base_url}/api/v1/rag/collections",
        headers={"Authorization": f"Bearer {jwt}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    collections = data if isinstance(data, list) else data.get("collections", [])
    for coll in collections:
        if coll.get("collection_name") == collection_name or coll.get("name") == collection_name:
            return int(coll["id"])
    return None


def _list_documents(base_url: str, jwt: str, collection_id: int) -> list[dict]:
    import requests
    resp = requests.get(
        f"{base_url}/api/v1/knowledge/repositories/{collection_id}/documents",
        headers={"Authorization": f"Bearer {jwt}"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("documents", [])


def _patch_document_source(
    base_url: str,
    jwt: str,
    collection_id: int,
    doc_id: str | int,
    source_uri: str,
    sync_interval: str = "daily",
) -> None:
    import requests
    resp = requests.patch(
        f"{base_url}/api/v1/knowledge/repositories/{collection_id}/documents/{doc_id}",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
        },
        json={
            "source_uri": source_uri,
            "sync_enabled": True,
            "sync_interval": sync_interval,
        },
        timeout=30,
    )
    resp.raise_for_status()


def _build_filename_to_path(source_files: list[dict]) -> dict[str, str]:
    """Map filename → rel_path for CDC source_uri wiring. Last writer wins on collision."""
    mapping: dict[str, str] = {}
    for f in source_files:
        mapping[f["filename"]] = f["rel_path"]
    return mapping


def do_import(pack_path: Path, source_files: list[dict]) -> None:
    """Phase 7: import the agentpack and wire CDC sync on every document."""
    base_url = os.environ.get("UDERIA_BASE_URL", "http://localhost:5050").rstrip("/")
    username = os.environ.get("UDERIA_USERNAME", "admin")
    password = os.environ.get("UDERIA_PASSWORD", "admin")

    print(f"\n{'='*60}")
    print("Phase 7 — Auto-import")
    print(f"{'='*60}")
    print(f"  Target : {base_url}")

    # Authenticate
    print("  Auth   : logging in …")
    jwt = _get_jwt(base_url, username, password)
    print("  Auth   : OK")

    # Import pack
    print(f"  Import : uploading {pack_path.name} …")
    import_result = _import_pack(base_url, jwt, pack_path)
    print(f"  Import : {import_result}")

    # Find the collection by name
    print(f"  Lookup : finding collection '{COLLECTION_NAME}' …")
    collection_id = _find_collection_id(base_url, jwt, COLLECTION_NAME)
    if collection_id is None:
        print(f"  WARN   : Collection '{COLLECTION_NAME}' not found after import.")
        print("           CDC sync wiring skipped — run manually if needed.")
        return
    print(f"  Lookup : collection_id = {collection_id}")

    # List documents
    print("  Docs   : listing documents …")
    documents = _list_documents(base_url, jwt, collection_id)
    print(f"  Docs   : {len(documents)} document(s) found")

    if not documents:
        print("  WARN   : No documents returned — CDC wiring skipped.")
        return

    # Build filename → abs_path mapping for source_uri wiring
    filename_to_path = _build_filename_to_path(source_files)

    # PATCH each document with source_uri + sync_enabled
    wired = 0
    skipped = 0
    for doc in documents:
        doc_id = doc.get("document_id") or doc.get("id")
        filename = doc.get("filename", "")
        rel_path = filename_to_path.get(filename)

        if not rel_path:
            print(f"  SKIP   : '{filename}' — no matching file path found")
            skipped += 1
            continue

        # Root-relative URI — resolved at sync time against the server's installation root
        source_uri = f"file://{rel_path}"
        try:
            _patch_document_source(base_url, jwt, collection_id, doc_id, source_uri)
            wired += 1
        except Exception as e:
            print(f"  ERROR  : PATCH failed for '{filename}' (doc={doc_id}): {e}")
            skipped += 1

    print(f"\n  CDC wiring complete: {wired} wired, {skipped} skipped")

    if wired == 0:
        print("  WARN   : No documents wired — skipping post-import steps.")
        return

    # Lock embedding model — all chunks were built in a single run with the same model
    print("  Lock   : setting embedding_model_locked=1 …")
    try:
        import requests as _req
        resp = _req.patch(
            f"{base_url}/api/v1/knowledge/repositories/{collection_id}",
            headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"},
            json={"embedding_model_locked": 1},
            timeout=15,
        )
        resp.raise_for_status()
        print("  Lock   : OK")
    except Exception as e:
        print(f"  WARN   : Could not lock embedding model: {e}")

    # Run initial sync to hash-check all files and clear the stale count
    print("  Sync   : initial hash-check to clear stale counter …")
    try:
        import requests as _req
        resp = _req.post(
            f"{base_url}/api/v1/knowledge/repositories/{collection_id}/sync",
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=120,
        )
        resp.raise_for_status()
        sync_result = resp.json()
        print(f"  Sync   : checked={sync_result.get('checked')} "
              f"unchanged={sync_result.get('unchanged')} "
              f"updated={sync_result.get('updated')} "
              f"errors={sync_result.get('errors')}")
    except Exception as e:
        print(f"  WARN   : Initial sync failed: {e}")

    print(f"\n  APScheduler will auto-sync this collection daily.")
    print(f"  Manual sync: POST {base_url}/api/v1/knowledge/repositories/{collection_id}/sync")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build uderia_expert.agentpack from all Uderia platform docs"
    )
    parser.add_argument(
        "--docs-root",
        type=str,
        default=str(PROJECT_ROOT),
        help="Project root (default: auto-detected from script location)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(Path(__file__).parent / "output"),
        help="Output directory (default: agent_packs/uderia_expert/output)",
    )
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="Auto-import into running Uderia instance + wire CDC sync",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even if output already exists",
    )
    args = parser.parse_args()

    project_root = Path(args.docs_root).resolve()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pack_path = output_dir / "uderia_expert.agentpack"

    if pack_path.exists() and not args.force and not args.do_import:
        print(f"Output already exists: {pack_path}")
        print("Use --force to rebuild or --import to import the existing pack.")
        sys.exit(0)

    # ── Phase 1: Scan ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Phase 1 — Scanning documentation")
    print(f"{'='*60}")
    print(f"  Root    : {project_root}")

    source_files = collect_source_files(project_root)
    print(f"  Found   : {len(source_files)} markdown file(s)")

    if not source_files:
        print("ERROR: No markdown files found. Check --docs-root.")
        sys.exit(1)

    # Show breakdown by category
    from collections import Counter
    counts = Counter(f["category"] for f in source_files)
    for cat, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"           {n:3d}  {cat}")

    if pack_path.exists() and not args.force:
        print(f"\nSkipping build — {pack_path.name} already exists (use --force to rebuild).")
        if args.do_import:
            do_import(pack_path, source_files)
        return

    # ── Phase 2–4: Chunk, embed, pack ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Phases 2–4 — Chunk / Embed / Pack")
    print(f"{'='*60}")

    print(f"  Loading embedding model: {EMBEDDING_MODEL} …")
    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"  Model ready ({model.get_sentence_embedding_dimension()}d)\n")

    collection_zip, stats = process_docs(source_files, model)

    # ── Phase 5: Manifest ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Phase 5 — Manifest")
    print(f"{'='*60}")

    manifest = build_manifest(stats)
    print(f"  Profile : {PROFILE_TAG} ({manifest['profiles'][0]['profile_type']})")
    print(f"  Collect : {COLLECTION_REF}")

    # ── Phase 6: Bundle .agentpack ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Phase 6 — Bundling .agentpack")
    print(f"{'='*60}")

    with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        arcname = f"collections/{COLLECTION_REF}.zip"
        zf.writestr(arcname, collection_zip)
        size_mb = len(collection_zip) / (1024 * 1024)
        print(f"  Added   : {arcname} ({size_mb:.1f} MB)")

    final_mb = pack_path.stat().st_size / (1024 * 1024)

    print(f"\n{'='*60}")
    print("BUILD SUMMARY")
    print(f"{'='*60}")
    print(f"  Pack       : {PACK_NAME} v{PACK_VERSION}")
    print(f"  Documents  : {stats['documents']}")
    print(f"  Chunks     : {stats['chunks']}")
    print(f"  Output     : {pack_path}")
    print(f"  Size       : {final_mb:.1f} MB")

    if args.do_import:
        do_import(pack_path, source_files)
    else:
        print(f"\nTo install manually:")
        print(f"  JWT=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \\")
        print(f"    -H 'Content-Type: application/json' \\")
        print(f"    -d '{{\"username\":\"admin\",\"password\":\"admin\"}}' | jq -r '.token')")
        print(f"  curl -X POST http://localhost:5050/api/v1/agent-packs/import \\")
        print(f"    -H \"Authorization: Bearer $JWT\" \\")
        print(f"    -F 'file=@{pack_path}' \\")
        print(f"    -F 'data={{\"conflict_strategy\":\"replace\"}}'")
        print(f"\nOr use: python {__file__} --import")


if __name__ == "__main__":
    main()
