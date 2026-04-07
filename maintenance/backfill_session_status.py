#!/usr/bin/env python3
"""
Backfill the 'status' column in session_index.db for all sessions
that currently have status='unknown'.

Reads each session's JSON file, derives the status from the last
valid workflow turn, and writes the updates.

Status values:
  empty   — session has no valid turns
  success — last turn completed successfully
  partial — last turn was cancelled
  failed  — last turn ended with an error

Usage:
    python maintenance/backfill_session_status.py [--dry-run]

If the database is root-owned (Docker), the script generates a SQL
patch file and prints the one-liner needed to apply it with sudo.
"""

import sys
import json
import shutil
import logging
import argparse
import sqlite3
import tempfile
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


def read_sessions_via_temp_copy() -> list:
    """Copy DB to /tmp and read from there (works when DB is root-owned)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    shutil.copy2(str(SESSION_INDEX_DB), tmp.name)
    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT session_id, user_uuid FROM session_index WHERE status = 'unknown'"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
        Path(tmp.name).unlink(missing_ok=True)


def backfill(dry_run: bool = False) -> bool:
    if not SESSION_INDEX_DB.exists():
        logger.error(f"session_index.db not found at {SESSION_INDEX_DB}")
        return False

    # Try direct read first; fall back to temp-copy if DB is root-owned
    try:
        conn = sqlite3.connect(f"file:{SESSION_INDEX_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT session_id, user_uuid FROM session_index WHERE status = 'unknown'"
        ).fetchall()]
        conn.close()
    except sqlite3.OperationalError:
        logger.debug("Direct read failed (root-owned DB), falling back to temp copy")
        rows = read_sessions_via_temp_copy()

    if not rows:
        print("✓ No sessions with status='unknown' found — nothing to do.")
        return True

    print(f"\nFound {len(rows)} session(s) with status='unknown'\n")

    updated = skipped = errors = 0
    updates: list[tuple[str, str]] = []  # (status, session_id)

    for row in rows:
        session_id = row["session_id"]
        user_uuid = row["user_uuid"]

        session_file = SESSIONS_DIR / user_uuid / f"{session_id}.json"
        if not session_file.exists():
            logger.warning(f"  ⚠  {session_id}: file not found, skipping")
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

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Results:")
    print(f"  ✓ Updated : {updated}")
    print(f"  ⚠  Skipped : {skipped}  (session file not found)")
    print(f"  ❌ Errors  : {errors}")

    if dry_run or not updates:
        return errors == 0

    # Try direct write first
    try:
        rw_conn = sqlite3.connect(str(SESSION_INDEX_DB))
        rw_conn.executemany(
            "UPDATE session_index SET status = ? WHERE session_id = ?",
            updates
        )
        rw_conn.commit()
        rw_conn.close()
        print(f"\n✓ Written directly to {SESSION_INDEX_DB}")
        return errors == 0
    except sqlite3.OperationalError:
        pass

    # DB is root-owned — write a SQL patch file and instruct the user
    sql_path = Path(tempfile.gettempdir()) / "backfill_session_status.sql"
    with open(sql_path, "w") as f:
        for status, session_id in updates:
            escaped = status.replace("'", "''")
            f.write(f"UPDATE session_index SET status = '{escaped}' WHERE session_id = '{session_id}';\n")

    print(f"\n⚠  Database is root-owned — cannot write directly.")
    print(f"   SQL patch written to: {sql_path}")
    print(f"\n   Apply it with:\n")
    print(f"   sudo sqlite3 {SESSION_INDEX_DB} < {sql_path}\n")

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
