#!/usr/bin/env python3
"""
Convert TheVirtualAccountTeam JSON corpus files into Uderia-compatible import ZIPs.

Each corpus file produces one ZIP containing:
  - collection_metadata.json  (collection configuration)
  - documents.json            (chunks with pre-computed embeddings)

Usage:
    python agent_packs/vat/import_vat_corpus.py --corpus-dir /path/to/Corpus --output-dir agent_packs/vat/import_output

Prerequisites:
    pip install sentence-transformers langchain-text-splitters
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
from pathlib import Path

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer


CORPUS_FILES = [
    "Product_Corpus.json",
    "Sales_Corpus.json",
    "CTF_Corpus.json",
    "UseCases_Corpus.json",
    "AIF_Corpus.json",
    "DS_Corpus.json",
    "Delivery_Corpus.json",
    "EVS_Corpus.json",
    "CSA_Corpus.json",
]

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def normalize_date(date_str: str) -> str:
    """Normalize truncated dates from corpus files to valid ISO format.

    Corpus CDATE/MDATE values are often truncated (e.g. '2026-01-21 18:',
    '2025-10-06 14:11:'). This pads missing components so datetime.fromisoformat()
    can parse them.
    """
    if not date_str or not date_str.strip():
        return ""
    s = date_str.strip().rstrip(":")
    # After stripping trailing colon, possible formats:
    #   '2026-01-21 18'        -> add ':00:00'
    #   '2025-10-06 14:11'     -> add ':00'
    #   '2025-10-06 14:11:30'  -> already complete
    #   '2025-10-06'           -> date only, fine as-is
    if " " in s:
        date_part, time_part = s.split(" ", 1)
        colons = time_part.count(":")
        if colons == 0:
            s = f"{date_part} {time_part}:00:00"
        elif colons == 1:
            s = f"{date_part} {time_part}:00"
    return s


def clean_title(file_field: str) -> str:
    """Extract a clean title from the FILE field."""
    # Remove file extension
    title = re.sub(r'\.[A-Za-z0-9]+$', '', file_field)
    # Remove SP codes like "- Internal - SP006054"
    title = re.sub(r'\s*-\s*(Internal|External|Confidential)\s*-\s*SP\d+', '', title)
    # Remove trailing " - Internal" etc.
    title = re.sub(r'\s*-\s*(Internal|External|Confidential)\s*$', '', title)
    return title.strip()


def corpus_display_name(corpus_filename: str) -> str:
    """Convert 'Product_Corpus.json' -> 'Product'."""
    return corpus_filename.replace("_Corpus.json", "")


def extract_document_text(doc: dict) -> str:
    """Extract all text content from a corpus document."""
    sections = []

    if "TRANSCRIPT" in doc and doc["TRANSCRIPT"]:
        sections.append(doc["TRANSCRIPT"])

    if "SLIDES" in doc and doc["SLIDES"]:
        slides = doc["SLIDES"]
        # Sort by slide number (keys are strings like "1", "2", ...)
        sorted_keys = sorted(slides.keys(), key=lambda k: int(k) if k.isdigit() else 0)
        slide_texts = []
        for key in sorted_keys:
            slide_texts.append(f"Slide {key}: {slides[key]}")
        sections.append("\n\n".join(slide_texts))

    if "CONTENT" in doc and doc["CONTENT"]:
        sections.append(doc["CONTENT"])

    return "\n\n".join(sections)


def process_corpus(corpus_path: Path, output_dir: Path, model: SentenceTransformer) -> dict:
    """Process a single corpus file into an import ZIP."""
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

        # Prepend source metadata into the chunk text for better retrieval
        header = f"Source: {file_field}\nDate: {date_str}\n\n"
        full_text = header + text

        chunks = splitter.split_text(full_text)

        # Stable document ID from FILE + array index (handles duplicate FILE values)
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{file_field}::{doc_idx}"))
        title = clean_title(file_field)

        for i, chunk_text in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            # Make chunk_id globally unique by adding a content hash suffix
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:8]
            chunk_id = f"{chunk_id}_{content_hash}"

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
        print(f"  WARNING: No chunks generated, skipping.")
        return None

    # Generate embeddings
    print(f"  Generating embeddings ({EMBEDDING_MODEL})...")
    embeddings = model.encode(all_chunks, show_progress_bar=True, batch_size=64)
    embeddings_list = embeddings.tolist()
    print(f"  Embeddings: {len(embeddings_list)} x {len(embeddings_list[0])}d")

    # Build collection_metadata.json
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
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Build documents.json
    documents_data = {
        "ids": all_ids,
        "documents": all_chunks,
        "metadatas": all_metadatas,
        "embeddings": embeddings_list,
    }

    # Create ZIP
    zip_name = f"{corpus_name}_Corpus_import.zip"
    zip_path = output_dir / zip_name

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("collection_metadata.json", json.dumps(collection_metadata, indent=2))
        zf.writestr("documents.json", json.dumps(documents_data))

    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  ZIP created: {zip_name} ({zip_size_mb:.1f} MB)")

    return {
        "corpus": corpus_filename,
        "name": f"VAT {corpus_name}",
        "documents": len(documents),
        "chunks": len(all_chunks),
        "zip_file": zip_name,
        "zip_size_mb": round(zip_size_mb, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Convert VAT corpus files to Uderia import ZIPs")
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
        help="Output directory for ZIP files",
    )
    args = parser.parse_args()

    corpus_dir = Path(args.corpus_dir)
    output_dir = Path(args.output_dir)

    if not corpus_dir.exists():
        print(f"ERROR: Corpus directory not found: {corpus_dir}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Verify all corpus files exist
    missing = []
    for f in CORPUS_FILES:
        if not (corpus_dir / f).exists():
            missing.append(f)
    if missing:
        print(f"ERROR: Missing corpus files: {', '.join(missing)}")
        sys.exit(1)

    # Load embedding model once
    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"Model loaded ({model.get_sentence_embedding_dimension()}d embeddings)")

    # Process each corpus
    results = []
    for corpus_file in CORPUS_FILES:
        corpus_path = corpus_dir / corpus_file
        result = process_corpus(corpus_path, output_dir, model)
        if result:
            results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total_docs = 0
    total_chunks = 0
    for r in results:
        print(f"  {r['name']:25s}  {r['documents']:4d} docs  {r['chunks']:5d} chunks  {r['zip_size_mb']:6.1f} MB")
        total_docs += r['documents']
        total_chunks += r['chunks']
    print(f"  {'TOTAL':25s}  {total_docs:4d} docs  {total_chunks:5d} chunks")
    print(f"\nZIP files written to: {output_dir}")

    # Save summary for next script
    summary_path = output_dir / "conversion_summary.json"
    with open(summary_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
