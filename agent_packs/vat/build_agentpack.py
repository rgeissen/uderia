#!/usr/bin/env python3
"""
Build a conforming .agentpack from TheVirtualAccountTeam corpus files.

This is a *bridge* script — it converts VAT-specific corpus JSON files into
a standard .agentpack artifact that the Uderia platform can import via
POST /api/v1/agent-packs/import.

The script:
1. Reads 9 corpus JSON files from TheVirtualAccountTeam/Corpus/
2. Chunks text with RecursiveCharacterTextSplitter
3. Computes embeddings with SentenceTransformer (all-MiniLM-L6-v2)
4. Writes each corpus as a collection ZIP (collection_metadata.json + documents.jsonl)
5. Generates manifest.json with expert definitions + collection refs
6. Bundles everything into vat.agentpack

Usage:
    python agent_packs/vat/build_agentpack.py --corpus-dir /path/to/Corpus

    # Or using the default corpus symlink:
    python agent_packs/vat/build_agentpack.py

Prerequisites:
    pip install sentence-transformers langchain-text-splitters numpy

Output:
    agent_packs/vat/import_output/vat.agentpack
"""

import argparse
import hashlib
import json
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
BATCH_SIZE = 5000  # Chunks per JSONL batch (matches collection_utils.py)
EMBED_BATCH_SIZE = 64

PACK_NAME = "Virtual Account Team"
PACK_DESCRIPTION = "Coordinates 9 specialized Teradata domain experts covering product, sales, competitive intelligence, use cases, systems, data science, delivery, agentic AI, and analytics."
PACK_AUTHOR = "Teradata"
PACK_VERSION = "2.0.0"

# Corpus files and their expert definitions
EXPERTS = [
    {
        "corpus_file": "Product_Corpus.json",
        "collection_ref": "product_knowledge",
        "collection_name": "VAT Product",
        "collection_description": "Product knowledge base — Teradata Vantage capabilities",
        "tag": "PRODUCT_SME",
        "name": "Product Expert",
        "description": "Expert for Teradata Vantage Platform capabilities including SQL engine, workload management, data integration, cloud connectivity, and QueryGrid.",
    },
    {
        "corpus_file": "Sales_Corpus.json",
        "collection_ref": "sales_knowledge",
        "collection_name": "VAT Sales",
        "collection_description": "Sales enablement knowledge base",
        "tag": "SALES_SME",
        "name": "Sales Advisor",
        "description": "Expert for Teradata sales enablement including objection handling, pricing guidance, deal strategy, account planning, and go-to-market motions.",
    },
    {
        "corpus_file": "UseCases_Corpus.json",
        "collection_ref": "usecases_knowledge",
        "collection_name": "VAT UseCases",
        "collection_description": "Customer use cases and success stories",
        "tag": "UCS_SME",
        "name": "Use Cases Expert",
        "description": "Expert for Teradata customer use cases, industry references, success stories, and solution patterns across verticals.",
    },
    {
        "corpus_file": "CTF_Corpus.json",
        "collection_ref": "ctf_knowledge",
        "collection_name": "VAT CTF",
        "collection_description": "Competitive intelligence knowledge base",
        "tag": "CTF_SME",
        "name": "Competitive Expert",
        "description": "Expert for Teradata competitive positioning including differentiation against Snowflake, Databricks, Google BigQuery, and other platforms.",
    },
    {
        "corpus_file": "Systems_Corpus.json",
        "collection_ref": "systems_knowledge",
        "collection_name": "VAT Systems",
        "collection_description": "Systems and infrastructure knowledge base",
        "tag": "SYS_SME",
        "name": "Systems Expert",
        "description": "Expert for Teradata Systems and Infrastructure including Artemis, AI Factory, Intelliflex, and Vantage Cloud Deployment.",
    },
    {
        "corpus_file": "DS_Corpus.json",
        "collection_ref": "ds_knowledge",
        "collection_name": "VAT DS",
        "collection_description": "Data science and AI/ML knowledge base",
        "tag": "DS_SME",
        "name": "Data Science Expert",
        "description": "Expert Data Scientist for AI/ML implementation patterns including model development, feature engineering, in-database analytics, and operationalization.",
    },
    {
        "corpus_file": "Delivery_Corpus.json",
        "collection_ref": "delivery_knowledge",
        "collection_name": "VAT Delivery",
        "collection_description": "Professional services and delivery knowledge base",
        "tag": "DEL_SME",
        "name": "Delivery Expert",
        "description": "Expert for Teradata Delivery Services including professional services, implementation methodology, migration, managed services, and customer onboarding.",
    },
    {
        "corpus_file": "Agentic_Corpus.json",
        "collection_ref": "agentic_knowledge",
        "collection_name": "VAT Agentic",
        "collection_description": "Agentic AI capabilities knowledge base",
        "tag": "AGT_SME",
        "name": "Agentic Expert",
        "description": "Expert for Teradata's Agentic AI Capabilities including Enterprise Vector Store, MCP Server, Agent Builder, and RAG Solutions.",
    },
    {
        "corpus_file": "CSA_Corpus.json",
        "collection_ref": "csa_knowledge",
        "collection_name": "VAT CSA",
        "collection_description": "ClearScape Analytics knowledge base",
        "tag": "CSA_SME",
        "name": "Analytics Expert",
        "description": "Expert for Teradata ClearScape Analytics - the advanced analytics portfolio including geospatial, time series, graph analytics, and open analytics integration.",
    },
]

SYNTHESIS_PROMPT = """You are a Principal Analyst at Teradata, an expert in synthesizing information into high-quality, client-facing documents. Your task is to create a polished response to the user's request using the provided raw context snippets.

**CRITICAL INSTRUCTIONS:**
1.  **Analyze the User's Goal:** First, understand the core objective of the user's query.
2.  **Filter for Relevance:** You MUST ignore any snippets that do not directly relate to the user's specific request.
3.  **Extract Key Facts:** From the relevant context, extract the most important facts, figures, and talking points.
4.  **Synthesize and Structure:** Write a comprehensive, well-structured answer that directly fulfills the user's request. Use clear headings, bullet points, and bold text (Markdown).
5.  **Cite Your Sources:** Create a numbered list of the unique 'Source' documents you used. As you write, cite information using numeric footnotes corresponding to your reference list (e.g., `[1]`, `[2]`).
6.  **Final Formatting:** At the very end of your response, you MUST add a section with the exact heading `### References`. Under this heading, paste the unique, numbered list of sources."""


# ── Utilities ─────────────────────────────────────────────────────────────────

def normalize_date(date_str: str) -> str:
    if not date_str or not date_str.strip():
        return ""
    s = date_str.strip().rstrip(":")
    if " " in s:
        date_part, time_part = s.split(" ", 1)
        colons = time_part.count(":")
        if colons == 0:
            s = f"{date_part} {time_part}:00:00"
        elif colons == 1:
            s = f"{date_part} {time_part}:00"
    return s


def clean_title(file_field: str) -> str:
    title = re.sub(r'\.[A-Za-z0-9]+$', '', file_field)
    title = re.sub(r'\s*-\s*(Internal|External|Confidential)\s*-\s*SP\d+', '', title)
    title = re.sub(r'\s*-\s*(Internal|External|Confidential)\s*$', '', title)
    return title.strip()


def extract_document_text(doc: dict) -> str:
    sections = []
    if "TRANSCRIPT" in doc and doc["TRANSCRIPT"]:
        sections.append(doc["TRANSCRIPT"])
    if "SLIDES" in doc and doc["SLIDES"]:
        slides = doc["SLIDES"]
        sorted_keys = sorted(slides.keys(), key=lambda k: int(k) if k.isdigit() else 0)
        for key in sorted_keys:
            sections.append(f"Slide {key}: {slides[key]}")
    if "CONTENT" in doc and doc["CONTENT"]:
        sections.append(doc["CONTENT"])
    return "\n\n".join(sections)


def corpus_display_name(corpus_filename: str) -> str:
    return corpus_filename.replace("_Corpus.json", "")


# ── Core Processing ──────────────────────────────────────────────────────────

def process_corpus(corpus_path: Path, model: SentenceTransformer) -> tuple[bytes, dict]:
    """Process a corpus file into a collection ZIP (in-memory bytes).

    Returns (zip_bytes, stats_dict).
    The ZIP contains collection_metadata.json + documents.jsonl (batched).
    """
    corpus_filename = corpus_path.name
    corpus_name = corpus_display_name(corpus_filename)

    print(f"\n{'='*60}")
    print(f"Processing: {corpus_filename}")
    print(f"{'='*60}")

    with open(corpus_path, 'r', encoding='utf-8') as f:
        documents = json.load(f)

    print(f"  Documents: {len(documents)}")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    all_chunks = []
    all_metadatas = []
    all_ids = []

    for doc_idx, doc in enumerate(documents):
        file_field = doc.get("FILE", "Unknown")
        cdate = doc.get("CDATE", "")
        mdate = doc.get("MDATE", "")
        date_str = normalize_date(mdate if mdate else cdate)

        text = extract_document_text(doc)
        if not text or not text.strip():
            continue

        header = f"Source: {file_field}\nDate: {date_str}\n\n"
        full_text = header + text
        chunks = splitter.split_text(full_text)

        doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{file_field}::{doc_idx}"))
        title = clean_title(file_field)

        for i, chunk_text in enumerate(chunks):
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:8]
            chunk_id = f"{doc_id}_chunk_{i}_{content_hash}"

            all_chunks.append(chunk_text)
            all_ids.append(chunk_id)
            all_metadatas.append({
                "document_id": doc_id,
                "filename": file_field,
                "title": title,
                "source": "import",
                "category": corpus_name,
                "tags": f"vat_import,{corpus_name}",
                "chunk_index": i,
                "chunk_method": "recursive",
                "document_type": "json",
                "created_at": date_str,
            })

    print(f"  Chunks: {len(all_chunks)}")
    if not all_chunks:
        print("  WARNING: No chunks generated, skipping.")
        return None, None

    # Generate embeddings
    print(f"  Generating embeddings ({EMBEDDING_MODEL})...")
    embeddings = model.encode(all_chunks, show_progress_bar=True, batch_size=EMBED_BATCH_SIZE)
    embeddings_list = embeddings.tolist()
    print(f"  Embeddings: {len(embeddings_list)} x {len(embeddings_list[0])}d")

    # Build collection metadata
    collection_metadata = {
        "export_version": "1.0",
        "name": f"VAT {corpus_name}",
        "description": f"Virtual Account Team - {corpus_name} knowledge base ({len(documents)} documents)",
        "repository_type": "knowledge",
        "embedding_model": EMBEDDING_MODEL,
        "chunking_strategy": "recursive",
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "document_count": len(documents),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }

    # Create ZIP in memory with documents.jsonl (batched format)
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("collection_metadata.json", json.dumps(collection_metadata, indent=2))

        # Write documents.jsonl — one batch per line
        jsonl_lines = []
        total = len(all_ids)
        for start in range(0, total, BATCH_SIZE):
            end = min(start + BATCH_SIZE, total)
            batch = {
                "ids": all_ids[start:end],
                "documents": all_chunks[start:end],
                "metadatas": all_metadatas[start:end],
                "embeddings": embeddings_list[start:end],
            }
            jsonl_lines.append(json.dumps(batch, allow_nan=False))
        zf.writestr("documents.jsonl", "\n".join(jsonl_lines) + "\n")

    zip_bytes = buf.getvalue()
    zip_size_mb = len(zip_bytes) / (1024 * 1024)
    print(f"  Collection ZIP: {zip_size_mb:.1f} MB ({len(jsonl_lines)} JSONL batches)")

    stats = {
        "documents": len(documents),
        "chunks": len(all_chunks),
        "zip_size_mb": round(zip_size_mb, 2),
    }
    return zip_bytes, stats


def build_manifest(expert_stats: dict[str, dict]) -> dict:
    """Build manifest.json for the .agentpack."""
    manifest = {
        "format_version": "1.0",
        "name": PACK_NAME,
        "description": PACK_DESCRIPTION,
        "author": PACK_AUTHOR,
        "version": PACK_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tags": ["teradata", "sales", "competitive", "product", "analytics"],
        "coordinator": {
            "tag": "VAT",
            "name": "Virtual Account Team",
            "description": "Coordinates specialized Teradata experts to answer complex queries. Routes questions to the right subject matter expert(s) and synthesizes comprehensive answers.",
            "profile_type": "genie",
            "classification_mode": "light",
            "genieConfig": {
                "temperature": 0.5,
                "queryTimeout": 600,
                "maxIterations": 15,
            },
        },
        "experts": [],
        "collections": [],
    }

    for expert in EXPERTS:
        ref = expert["collection_ref"]
        stats = expert_stats.get(ref)

        # Expert definition
        expert_entry = {
            "tag": expert["tag"],
            "name": expert["name"],
            "description": expert["description"],
            "profile_type": "rag_focused",
            "collection_ref": ref,
            "classification_mode": "light",
            "knowledgeConfig": {
                "maxDocs": 10,
                "maxTokens": 8000,
                "minRelevanceScore": 0.25,
                "maxChunksPerDocument": 2,
                "freshnessWeight": 0.5,
                "freshnessDecayRate": 0.005,
            },
            "synthesisPromptOverride": SYNTHESIS_PROMPT,
        }
        manifest["experts"].append(expert_entry)

        # Collection definition
        coll_entry = {
            "ref": ref,
            "file": f"collections/{ref}.zip",
            "name": expert["collection_name"],
            "repository_type": "knowledge",
            "description": expert["collection_description"],
        }
        if stats:
            coll_entry["documents"] = stats["documents"]
            coll_entry["chunks"] = stats["chunks"]
        manifest["collections"].append(coll_entry)

    # Add External SME profile (no collection — uses external MCP server)
    manifest["experts"].append({
        "tag": "EXTERNAL_SME",
        "name": "External Research",
        "description": "Expert for finding external, public information via internet search. Used when internal knowledge is insufficient or the query requires current public data.",
        "profile_type": "tool_enabled",
        "classification_mode": "light",
        "mcpServerName": "Google Search",
    })

    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Build vat.agentpack from TheVirtualAccountTeam corpus files"
    )
    parser.add_argument(
        "--corpus-dir",
        type=str,
        default=str(Path(__file__).parent / "corpus"),
        help="Path to directory containing *_Corpus.json files",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(Path(__file__).parent / "import_output"),
        help="Output directory for the .agentpack file",
    )
    args = parser.parse_args()

    corpus_dir = Path(args.corpus_dir)
    output_dir = Path(args.output_dir)

    if not corpus_dir.exists():
        print(f"ERROR: Corpus directory not found: {corpus_dir}")
        print("Provide --corpus-dir pointing to TheVirtualAccountTeam/Corpus/")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Verify all corpus files
    missing = [e["corpus_file"] for e in EXPERTS if not (corpus_dir / e["corpus_file"]).exists()]
    if missing:
        print(f"ERROR: Missing corpus files: {', '.join(missing)}")
        sys.exit(1)

    # Load embedding model once
    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"Model loaded ({model.get_sentence_embedding_dimension()}d embeddings)\n")

    # Process each corpus
    collection_zips: dict[str, bytes] = {}  # ref -> zip bytes
    expert_stats: dict[str, dict] = {}  # ref -> stats

    for expert in EXPERTS:
        corpus_path = corpus_dir / expert["corpus_file"]
        ref = expert["collection_ref"]

        zip_bytes, stats = process_corpus(corpus_path, model)
        if zip_bytes:
            collection_zips[ref] = zip_bytes
            expert_stats[ref] = stats

    if not collection_zips:
        print("\nERROR: No collections generated. Cannot build .agentpack.")
        sys.exit(1)

    # Build manifest
    manifest = build_manifest(expert_stats)

    # Bundle into .agentpack
    agentpack_path = output_dir / "vat.agentpack"
    print(f"\n{'='*60}")
    print("Bundling vat.agentpack")
    print(f"{'='*60}")

    with zipfile.ZipFile(agentpack_path, 'w', zipfile.ZIP_STORED) as zf:
        # Collections are already compressed internally — use STORED to avoid
        # double-compression overhead (negligible size difference, faster I/O)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        for ref, zip_bytes in collection_zips.items():
            arcname = f"collections/{ref}.zip"
            zf.writestr(arcname, zip_bytes)
            size_mb = len(zip_bytes) / (1024 * 1024)
            print(f"  Added: {arcname} ({size_mb:.1f} MB)")

    final_size_mb = agentpack_path.stat().st_size / (1024 * 1024)

    # Summary
    print(f"\n{'='*60}")
    print("BUILD SUMMARY")
    print(f"{'='*60}")
    print(f"  Pack:        {PACK_NAME} v{PACK_VERSION}")
    print(f"  Experts:     {len(manifest['experts'])}")
    print(f"  Collections: {len(collection_zips)}")
    total_chunks = sum(s["chunks"] for s in expert_stats.values())
    total_docs = sum(s["documents"] for s in expert_stats.values())
    print(f"  Documents:   {total_docs}")
    print(f"  Chunks:      {total_chunks}")
    print(f"  Output:      {agentpack_path}")
    print(f"  Size:        {final_size_mb:.1f} MB")
    print(f"\nTo install:")
    print(f"  curl -X POST http://localhost:5050/api/v1/agent-packs/import \\")
    print(f"       -H 'Authorization: Bearer $JWT' \\")
    print(f"       -F 'file=@{agentpack_path}'")


if __name__ == "__main__":
    main()
