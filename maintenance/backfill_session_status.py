#!/usr/bin/env python3
"""
Backfill the 'status' column in session_index.db for all sessions
that currently have status='unknown'.

Reads each session's JSON file, derives the status from the last
valid workflow turn, and updates the index.

Status values:
  empty   — session has no valid turns
  success — last turn completed successfully
  partial — last turn was cancelled
  failed  — last turn ended with an error

Usage:
    python maintenance/backfill_session_status.py [--dry-run]
"""

import sys
import json
import logging
import argparse
import sqlite3
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SESSIONS_DIR = Path(__file__).parent.parent / "tda_sessions"
SESSION_INDEX_DB = SESSIONS_DIR / "session_index.db"


def compute_session_status(wf: list) -> str:
    """Derive session status from workflow history turns."""
    valid_turns = [t for t in wf if t.get("isValid", True)]
    if not valid_turns:
        return "empty"
    last_status = valid_turns[-1].get("status", "success")
    if last_status == "error":
        return "failed"
    if last_status == "cancelled":
        return "partial"
    return "success"


def backfill(dry_run: bool = False) -> bool:
    if not SESSION_INDEX_DB.exists():
        logger.error(f"session_index.db not found at {SESSION_INDEX_DB}")
        return False

    # Open read-only for the initial scan (works even when DB is owned by Docker user)
    ro_conn = sqlite3.connect(f"file:{SESSION_INDEX_DB}?mode=ro", uri=True)
    ro_conn.row_factory = sqlite3.Row
    try:
        rows = ro_conn.execute(
            "SELECT session_id, user_uuid FROM session_index WHERE status = 'unknown'"
        ).fetchall()
    finally:
        ro_conn.close()

    if not rows:
        print("✓ No sessions with status='unknown' found — nothing to do.")
        return True

    print(f"\nFound {len(rows)} session(s) with status='unknown'\n")

    updated = skipped = errors = 0
    updates: list[tuple[str, str]] = []  # (status, session_id)

    for row in rows:
        session_id = row["session_id"]
        user_uuid = row["user_uuid"]

        # Locate the session JSON file
        session_file = SESSIONS_DIR / user_uuid / f"{session_id}.json"
        if not session_file.exists():
            logger.warning(f"  ⚠  {session_id}: file not found at {session_file}, skipping")
            skipped += 1
            continue

        try:
            with open(session_file, "r", encoding="utf-8") as f:
                session_data = json.load(f)
        except Exception as e:
            logger.error(f"  ❌ {session_id}: failed to read JSON — {e}")
            errors += 1
            continue

        wf = session_data.get("last_turn_data", {}).get("workflow_history", [])
        status = compute_session_status(wf)

        name = session_data.get("name", "Untitled")
        print(f"  {'[DRY-RUN] ' if dry_run else ''}{session_id[:8]}… \"{name}\" → {status}")

        updates.append((status, session_id))
        updated += 1

    if not dry_run and updates:
        # Open read-write only when we actually need to write
        rw_conn = sqlite3.connect(str(SESSION_INDEX_DB))
        try:
            rw_conn.executemany(
                "UPDATE session_index SET status = ? WHERE session_id = ?",
                updates
            )
            rw_conn.commit()
        finally:
            rw_conn.close()

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Results:")
    print(f"  ✓ Updated : {updated}")
    print(f"  ⚠  Skipped : {skipped}  (session file not found)")
    print(f"  ❌ Errors  : {errors}")

    return errors == 0


def main():
    parser = argparse.ArgumentParser(description="Backfill session_index status column")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be updated without writing to the database"
    )
    args = parser.parse_args()

    if args.dry_run:
        print("--- DRY RUN --- (no changes will be written)\n")

    try:
        success = backfill(dry_run=args.dry_run)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
