#!/usr/bin/env python3
"""
E2E Test: PDF Embedding via Teradata Server-Side Chunking

Exercises the full knowledge repository pipeline using REST API calls:
  1. Authenticate
  2. Discover Teradata vector store config
  3. Create knowledge repository
  4. Generate & upload a small test PDF (server-side chunking)
  5. Verify document listing
  6. Semantic search against embedded content
  7. Cleanup

Usage:
    python test/test_e2e_teradata_pdf.py [options]

Options:
    --base-url URL        Uderia server URL (default: http://localhost:5050)
    --username USER       Login username (default: admin)
    --password PASS       Login password (default: admin)
    --vs-config-id ID     Vector store config ID (auto-discovers if omitted)
    --keep                Skip cleanup (keep the test repository)
    --timeout SECONDS     Max wait for ingestion (default: 600)
"""

import argparse
import json
import os
import sys
import tempfile
import time

import requests


# ── Helpers ──────────────────────────────────────────────────────────────────

def step(num, total, msg):
    print(f"\n[{num}/{total}] {msg}", flush=True)


def fail(msg):
    print(f"\n  FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg="OK"):
    print(f"  {msg}", flush=True)


def headers(jwt):
    return {"Authorization": f"Bearer {jwt}"}


def parse_sse_stream(response):
    """Yield (event_type, data_dict) tuples from an SSE stream."""
    event_type = "message"
    for line in response.iter_lines(decode_unicode=True):
        if line is None:
            continue
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            raw = line[len("data:"):].strip()
            try:
                yield event_type, json.loads(raw)
            except json.JSONDecodeError:
                yield event_type, {"raw": raw}
        elif line == "":
            event_type = "message"


# ── PDF Generation ───────────────────────────────────────────────────────────

def generate_test_pdf(path: str):
    """Create a small 2-page PDF with known searchable content."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Page 1
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(w=0, h=10, text="Uderia E2E Test Document", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(w=0, h=7, text=(
        "This document is used for automated end-to-end testing of the "
        "Uderia Platform knowledge repository with Teradata Enterprise "
        "Vector Store server-side chunking.\n\n"
        "The capital of France is Paris. Paris is known for the Eiffel Tower, "
        "the Louvre Museum, and Notre-Dame Cathedral. France is a country in "
        "Western Europe with a population of approximately 67 million people.\n\n"
        "The capital of Germany is Berlin. Berlin is known for the Brandenburg "
        "Gate, the Berlin Wall, and Museum Island."
    ))

    # Page 2
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(w=0, h=10, text="Technical Details", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(w=0, h=7, text=(
        "Teradata Vantage is an enterprise analytics platform that supports "
        "advanced analytics including vector search capabilities. The Enterprise "
        "Vector Store (EVS) enables semantic search over unstructured data by "
        "combining document chunking, embedding generation via Amazon Bedrock, "
        "and approximate nearest neighbor search using the VECTORDISTANCE algorithm.\n\n"
        "Server-side chunking delegates all text extraction, chunking, and "
        "embedding to the Teradata platform. The client only needs to upload "
        "the raw PDF file."
    ))

    pdf.output(path)


# ── Test Steps ───────────────────────────────────────────────────────────────

def authenticate(base_url: str, username: str, password: str) -> str:
    step(1, 8, "Authenticating...")
    resp = requests.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    if resp.status_code != 200:
        fail(f"Login failed ({resp.status_code}): {resp.text}")
    jwt = resp.json().get("token")
    if not jwt:
        fail(f"No token in login response: {resp.json()}")
    ok(f"JWT obtained ({jwt[:40]}...)")
    return jwt


def discover_vs_config(base_url: str, jwt: str, vs_config_id: str | None) -> str:
    step(2, 8, "Discovering Teradata vector store config...")
    resp = requests.get(
        f"{base_url}/api/v1/vectorstore/configurations",
        headers=headers(jwt),
        timeout=15,
    )
    if resp.status_code != 200:
        fail(f"Failed to list VS configs ({resp.status_code}): {resp.text}")

    configs = resp.json().get("configurations", [])
    if not configs:
        fail("No vector store configurations found. Create one in Setup -> Vector Store first.")

    # If user specified a config ID, find it
    if vs_config_id:
        match = [c for c in configs if c.get("id") == vs_config_id]
        if not match:
            available = [f"  - {c['id']} ({c.get('name', 'unnamed')}, {c.get('backend_type')})" for c in configs]
            fail(f"Config '{vs_config_id}' not found. Available:\n" + "\n".join(available))
        cfg = match[0]
    else:
        # Auto-discover first Teradata config
        td_configs = [c for c in configs if c.get("backend_type") == "teradata"]
        if not td_configs:
            available = [f"  - {c['id']} ({c.get('name', 'unnamed')}, {c.get('backend_type')})" for c in configs]
            fail("No Teradata vector store config found. Available:\n" + "\n".join(available))
        cfg = td_configs[0]

    config_id = cfg["id"]
    ok(f"Found: {config_id} ({cfg.get('name', 'unnamed')}, backend={cfg.get('backend_type')})")
    return config_id


def create_knowledge_repo(base_url: str, jwt: str, vs_config_id: str) -> int:
    step(3, 8, "Creating knowledge repository...")
    repo_name = f"e2e_teradata_pdf_test_{int(time.time())}"
    resp = requests.post(
        f"{base_url}/api/v1/rag/collections",
        headers=headers(jwt),
        json={
            "name": repo_name,
            "description": "E2E test - Teradata server-side PDF embedding",
            "repository_type": "knowledge",
            "vector_store_config_id": vs_config_id,
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        fail(f"Failed to create repo ({resp.status_code}): {resp.text}")

    data = resp.json()
    collection_id = data.get("collection_id")
    if not collection_id:
        fail(f"No collection_id in response: {data}")
    ok(f"Created '{repo_name}' (ID: {collection_id}, backend: {data.get('backend_type', '?')})")
    return collection_id


def upload_pdf(base_url: str, jwt: str, collection_id: int, pdf_path: str, timeout_s: int):
    step(5, 8, "Uploading PDF (server-side chunking)...")

    with open(pdf_path, "rb") as f:
        resp = requests.post(
            f"{base_url}/api/v1/knowledge/repositories/{collection_id}/documents",
            headers=headers(jwt),
            files={"file": ("uderia_e2e_test.pdf", f, "application/pdf")},
            data={
                "chunking_strategy": "server_side",
                "chunk_size": "500",
                "optimized_chunking": "true",
                "title": "Uderia E2E Test Document",
                "category": "test",
            },
            stream=True,
            timeout=timeout_s,
        )

    if resp.status_code != 200:
        fail(f"Upload request failed ({resp.status_code}): {resp.text}")

    # Parse SSE stream
    completed = False
    error_msg = None
    last_msg = ""

    for event_type, data in parse_sse_stream(resp):
        msg = data.get("message", data.get("raw", ""))
        pct = data.get("percentage", "")
        evt_type = data.get("type", event_type)

        if evt_type == "progress" or event_type == "progress":
            pct_str = f" ({pct}%)" if pct else ""
            if msg != last_msg:
                print(f"       {msg}{pct_str}", flush=True)
                last_msg = msg

        elif evt_type == "complete" or event_type == "complete":
            completed = True
            doc_id = data.get("document_id", "?")
            ok(f"Complete! Document ID: {doc_id}")
            break

        elif evt_type == "error" or event_type == "error":
            error_msg = msg
            break

    if error_msg:
        fail(f"Server-side chunking error: {error_msg}")
    if not completed:
        fail("SSE stream ended without a 'complete' event")


def list_documents(base_url: str, jwt: str, collection_id: int):
    step(6, 8, "Listing documents...")
    resp = requests.get(
        f"{base_url}/api/v1/knowledge/repositories/{collection_id}/documents",
        headers=headers(jwt),
        timeout=15,
    )
    if resp.status_code != 200:
        fail(f"List documents failed ({resp.status_code}): {resp.text}")

    data = resp.json()
    docs = data.get("documents", [])
    if not docs:
        fail("No documents found in repository after upload")

    doc = docs[0]
    ok(f"{len(docs)} document(s) found: '{doc.get('filename', '?')}' "
       f"(size: {doc.get('file_size', '?')} bytes)")


def search_repository(base_url: str, jwt: str, collection_id: int):
    step(7, 8, "Searching 'capital of France'...")
    resp = requests.post(
        f"{base_url}/api/v1/knowledge/repositories/{collection_id}/search",
        headers=headers(jwt),
        json={"query": "What is the capital of France?", "k": 5},
        timeout=30,
    )
    if resp.status_code != 200:
        fail(f"Search failed ({resp.status_code}): {resp.text}")

    data = resp.json()
    results = data.get("results", [])
    if not results:
        fail("Search returned no results")

    top = results[0]
    distance = top.get("distance", "?")
    content_preview = (top.get("content", "")[:120] + "...") if top.get("content") else "?"
    ok(f"{len(results)} result(s), top distance: {distance}")
    print(f"       Content preview: \"{content_preview}\"", flush=True)

    # Soft check: the word "Paris" should appear somewhere in results
    all_content = " ".join(r.get("content", "") for r in results)
    if "Paris" in all_content:
        print("       'Paris' found in search results", flush=True)
    else:
        print("       WARNING: 'Paris' not found in results (may be chunked differently)", flush=True)


def cleanup(base_url: str, jwt: str, collection_id: int, keep: bool):
    step(8, 8, "Cleanup...")
    if keep:
        ok(f"Skipped (--keep). Repository {collection_id} preserved for inspection.")
        return

    resp = requests.delete(
        f"{base_url}/api/v1/rag/collections/{collection_id}",
        headers=headers(jwt),
        timeout=60,
    )
    if resp.status_code == 200:
        ok(f"Deleted repository {collection_id}")
    else:
        print(f"  WARNING: Cleanup returned {resp.status_code}: {resp.text}", flush=True)
        print(f"  You may need to manually delete collection {collection_id}", flush=True)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="E2E test: PDF embedding via Teradata server-side chunking"
    )
    parser.add_argument("--base-url", default="http://localhost:5050",
                        help="Uderia server URL (default: http://localhost:5050)")
    parser.add_argument("--username", default="admin",
                        help="Login username (default: admin)")
    parser.add_argument("--password", default="admin",
                        help="Login password (default: admin)")
    parser.add_argument("--vs-config-id", default=None,
                        help="Vector store config ID (auto-discovers first Teradata config if omitted)")
    parser.add_argument("--keep", action="store_true",
                        help="Skip cleanup (keep the test repository)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Max seconds to wait for ingestion (default: 600)")
    args = parser.parse_args()

    print("=" * 60)
    print("  Uderia E2E Test: Teradata Server-Side PDF Embedding")
    print("=" * 60)
    print(f"  Server:  {args.base_url}")
    print(f"  User:    {args.username}")
    print(f"  Timeout: {args.timeout}s")

    collection_id = None
    jwt = None

    try:
        # Step 1: Authenticate
        jwt = authenticate(args.base_url, args.username, args.password)

        # Step 2: Discover Teradata VS config
        vs_config_id = discover_vs_config(args.base_url, jwt, args.vs_config_id)

        # Step 3: Create knowledge repository
        collection_id = create_knowledge_repo(args.base_url, jwt, vs_config_id)

        # Step 4: Generate test PDF
        step(4, 8, "Generating test PDF...")
        pdf_path = os.path.join(tempfile.gettempdir(), "uderia_e2e_test.pdf")
        generate_test_pdf(pdf_path)
        file_size = os.path.getsize(pdf_path)
        ok(f"{pdf_path} ({file_size:,} bytes, 2 pages)")

        # Step 5: Upload PDF with server-side chunking
        upload_pdf(args.base_url, jwt, collection_id, pdf_path, args.timeout)

        # Step 6: Verify document listing
        list_documents(args.base_url, jwt, collection_id)

        # Step 7: Semantic search
        search_repository(args.base_url, jwt, collection_id)

        # Step 8: Cleanup
        cleanup(args.base_url, jwt, collection_id, args.keep)

        print("\n" + "=" * 60)
        print("  ALL TESTS PASSED")
        print("=" * 60)

    except SystemExit:
        # fail() calls sys.exit — still attempt cleanup
        if collection_id and jwt and not args.keep:
            print("\n  Attempting cleanup after failure...", flush=True)
            try:
                cleanup(args.base_url, jwt, collection_id, False)
            except Exception as e:
                print(f"  Cleanup error: {e}", flush=True)
        raise

    except Exception as exc:
        print(f"\n  UNEXPECTED ERROR: {exc}", file=sys.stderr)
        if collection_id and jwt and not args.keep:
            print("  Attempting cleanup...", flush=True)
            try:
                cleanup(args.base_url, jwt, collection_id, False)
            except Exception as e:
                print(f"  Cleanup error: {e}", flush=True)
        sys.exit(1)

    finally:
        # Clean up temp PDF
        pdf_path = os.path.join(tempfile.gettempdir(), "uderia_e2e_test.pdf")
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)


if __name__ == "__main__":
    main()
