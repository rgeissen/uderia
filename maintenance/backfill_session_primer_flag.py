#!/usr/bin/env python3
"""
Migration script to backfill is_session_primer flag in existing ChromaDB cases.

This script adds the is_session_primer field to all existing RAG cases in ChromaDB.
Cases are classified as session primers based on:
- Query length > 200 characters
- Presence of primer keywords ("Educate yourself", "Conversion Rules", "don't create sql", "leave this up to")

Usage:
    # Dry run (default) - show what would be changed
    python maintenance/backfill_session_primer_flag.py --dry-run

    # Execute - actually update ChromaDB
    python maintenance/backfill_session_primer_flag.py --execute

    # Show statistics only
    python maintenance/backfill_session_primer_flag.py --stats
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trusted_data_agent.agent.rag_retriever import RAGRetriever
from trusted_data_agent.core.config import APP_CONFIG

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Session primer detection keywords
PRIMER_KEYWORDS = [
    "educate yourself",
    "conversion rules",
    "don't create sql",
    "leave this up to",
    "if you get a request",
    "please follow the following"
]


def is_likely_primer(user_query: str) -> bool:
    """
    Determine if a user query is likely a session primer.

    Args:
        user_query: The user query text

    Returns:
        True if likely a primer, False otherwise
    """
    if not user_query:
        return False

    # Check length (session primers are typically very long)
    if len(user_query) > 200:
        return True

    # Check for primer keywords (case-insensitive)
    query_lower = user_query.lower()
    for keyword in PRIMER_KEYWORDS:
        if keyword in query_lower:
            return True

    return False


def backfill_collection(
    collection,
    collection_id: int,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Backfill is_session_primer flag for a single collection.

    Args:
        collection: ChromaDB collection object
        collection_id: Collection ID
        dry_run: If True, don't actually update (just report)

    Returns:
        Statistics dict with counts
    """
    stats = {
        "total_cases": 0,
        "missing_field": 0,
        "marked_as_primer": 0,
        "marked_as_not_primer": 0,
        "already_has_field": 0,
        "errors": 0
    }

    try:
        # Get all embeddings in collection
        results = collection.get(
            include=["metadatas"]
        )

        if not results or not results.get("metadatas"):
            logger.info(f"  Collection {collection_id} ({collection.name}): No cases found")
            return stats

        stats["total_cases"] = len(results["metadatas"])
        logger.info(f"  Collection {collection_id} ({collection.name}): {stats['total_cases']} total cases")

        # Process each case
        updates = []  # List of (id, new_metadata) tuples

        for idx, (case_id, metadata) in enumerate(zip(results["ids"], results["metadatas"])):
            # Check if field already exists
            if "is_session_primer" in metadata:
                stats["already_has_field"] += 1
                continue

            stats["missing_field"] += 1

            # Get user_query
            user_query = metadata.get("user_query", "")

            # Classify
            is_primer = is_likely_primer(user_query)

            if is_primer:
                stats["marked_as_primer"] += 1
                if not dry_run:
                    # Create updated metadata
                    updated_metadata = metadata.copy()
                    updated_metadata["is_session_primer"] = True
                    updates.append((case_id, updated_metadata))

                # Log the primer for review
                truncated = user_query if len(user_query) <= 100 else user_query[:97] + "..."
                logger.info(f"    [PRIMER] Case {case_id}: '{truncated}'")
            else:
                stats["marked_as_not_primer"] += 1
                if not dry_run:
                    # Create updated metadata
                    updated_metadata = metadata.copy()
                    updated_metadata["is_session_primer"] = False
                    updates.append((case_id, updated_metadata))

        # Apply updates if not dry run (batch to avoid ChromaDB size limits)
        if not dry_run and updates:
            BATCH_SIZE = 5000  # ChromaDB max is ~5461, use 5000 for safety
            total_updates = len(updates)
            logger.info(f"  Updating {total_updates} cases in batches of {BATCH_SIZE}...")

            for batch_start in range(0, total_updates, BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, total_updates)
                batch = updates[batch_start:batch_end]

                ids_to_update = [u[0] for u in batch]
                metadatas_to_update = [u[1] for u in batch]

                try:
                    collection.update(
                        ids=ids_to_update,
                        metadatas=metadatas_to_update
                    )
                    logger.info(f"    Batch {batch_start//BATCH_SIZE + 1}: Updated {len(batch)} cases ({batch_start+1}-{batch_end})")
                except Exception as e:
                    logger.error(f"    Batch {batch_start//BATCH_SIZE + 1} failed: {e}")
                    stats["errors"] += 1

            logger.info(f"  ✅ Updated {total_updates} cases")

    except Exception as e:
        logger.error(f"  ❌ Error processing collection {collection_id}: {e}", exc_info=True)
        stats["errors"] += 1

    return stats


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill is_session_primer flag in ChromaDB",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually update ChromaDB (default is dry-run)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry run mode - show what would be changed (default)"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show statistics only (no detailed logging)"
    )

    args = parser.parse_args()

    # Determine mode
    if args.execute:
        dry_run = False
        mode = "EXECUTE"
    else:
        dry_run = True
        mode = "DRY RUN"

    if args.stats:
        logger.setLevel(logging.WARNING)  # Only show summary

    # Start
    logger.info("=" * 80)
    logger.info(f"ChromaDB Session Primer Backfill - {mode} MODE")
    logger.info("=" * 80)

    if dry_run:
        logger.info("⚠️  DRY RUN MODE - No changes will be made")
        logger.info("    Use --execute to actually update ChromaDB")
    else:
        logger.warning("🔥 EXECUTE MODE - ChromaDB will be updated!")

    logger.info("")

    # Initialize RAG retriever
    logger.info("Initializing RAG retriever...")
    retriever = RAGRetriever(
        rag_cases_dir=APP_CONFIG.RAG_CASES_DIR,
        embedding_model_name=APP_CONFIG.RAG_EMBEDDING_MODEL,
        persist_directory=APP_CONFIG.RAG_PERSIST_DIR
    )

    logger.info(f"Found {len(retriever.collections)} collections")
    logger.info("")

    # Process each collection
    global_stats = {
        "total_cases": 0,
        "missing_field": 0,
        "marked_as_primer": 0,
        "marked_as_not_primer": 0,
        "already_has_field": 0,
        "errors": 0
    }

    for coll_id, collection in retriever.collections.items():
        logger.info(f"Processing Collection {coll_id} ({collection.name})...")
        stats = backfill_collection(collection, coll_id, dry_run)

        # Aggregate stats
        for key in global_stats:
            global_stats[key] += stats[key]

        logger.info("")

    # Print summary
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total cases:              {global_stats['total_cases']:,}")
    logger.info(f"Already have field:       {global_stats['already_has_field']:,}")
    logger.info(f"Missing field:            {global_stats['missing_field']:,}")
    logger.info(f"  - Marked as primer:     {global_stats['marked_as_primer']:,}")
    logger.info(f"  - Marked as not primer: {global_stats['marked_as_not_primer']:,}")
    logger.info(f"Errors:                   {global_stats['errors']:,}")
    logger.info("=" * 80)

    if dry_run:
        logger.info("")
        logger.info("⚠️  DRY RUN - No changes were made")
        logger.info("    Run with --execute to apply these changes")
    else:
        logger.info("")
        logger.info("✅ Migration complete!")

        # Save summary to file
        summary_file = Path(__file__).parent / "backfill_session_primer_flag.log"
        with open(summary_file, "w") as f:
            f.write(f"ChromaDB Session Primer Backfill - {datetime.now().isoformat()}\n")
            f.write("=" * 80 + "\n")
            f.write(f"Total cases:              {global_stats['total_cases']:,}\n")
            f.write(f"Already have field:       {global_stats['already_has_field']:,}\n")
            f.write(f"Missing field:            {global_stats['missing_field']:,}\n")
            f.write(f"  - Marked as primer:     {global_stats['marked_as_primer']:,}\n")
            f.write(f"  - Marked as not primer: {global_stats['marked_as_not_primer']:,}\n")
            f.write(f"Errors:                   {global_stats['errors']:,}\n")
        logger.info(f"Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
