#!/usr/bin/env python3
"""
VAT Agent Pack Pipeline — automated content-to-agentpack workflow.

Detects new/changed content in CorpContent, processes it with corpus_tools,
builds an updated vat.agentpack, and imports it into a running Uderia instance.

Usage:
    python agent_packs/vat/pipeline.py                          # Manual run
    python agent_packs/vat/pipeline.py --if-changed             # Cron mode (exit 0 if nothing new)
    python agent_packs/vat/pipeline.py --watch --interval 3600  # Polling loop
    python agent_packs/vat/pipeline.py --force                  # Force full rebuild
    python agent_packs/vat/pipeline.py --dry-run                # Detect changes only
    python agent_packs/vat/pipeline.py --skip-content           # Skip corpus processing

Prerequisites:
    - pipeline_config.json in this directory (copy from pipeline_config.example.json)
    - corpus_tools venv with Whisper, python-pptx, PyPDF2 etc.
    - Uderia venv with sentence-transformers, langchain-text-splitters
    - Uderia server running for import step
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Constants ────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]  # uderia/
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "pipeline_config.json"
LOG_PATH = SCRIPT_DIR / "pipeline_runs.log"

# File extensions that corpus_tools can process
SUPPORTED_EXTENSIONS = {
    ".pptx", ".ppt", ".pdf", ".docx", ".doc",
    ".mp4", ".m4a", ".m4v", ".mp3", ".wav", ".mov",
    ".txt", ".rtf", ".xlsx", ".html",
}

# VAT profile tags for verification
VAT_EXPERT_TAGS = {
    "PRODUCT_SME", "SALES_SME", "UCS_SME", "CTF_SME", "SYS_SME",
    "DS_SME", "DEL_SME", "AGT_SME", "CSA_SME",
}
VAT_COORDINATOR_TAG = "VAT"
ALL_VAT_TAGS = VAT_EXPERT_TAGS | {VAT_COORDINATOR_TAG}

IMPORT_RETRY_COUNT = 3
IMPORT_RETRY_DELAY = 10  # seconds
CONTENT_TIMEOUT = 1800   # 30 min per category (Whisper can be slow)

logger = logging.getLogger("vat_pipeline")


# ── Configuration ────────────────────────────────────────────────────────────

def load_config(config_path: Path, *, cli_overrides: dict | None = None) -> dict:
    """Load and validate pipeline configuration.

    Credential resolution order (highest wins):
        CLI args → environment variables → config file
    """
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}")
        print(f"Copy pipeline_config.example.json to pipeline_config.json and edit paths.")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    overrides = cli_overrides or {}

    # Resolve Uderia connection: CLI > env > config
    config["uderia_base_url"] = (
        overrides.get("base_url")
        or os.environ.get("UDERIA_BASE_URL")
        or config.get("uderia_base_url", "http://localhost:5050")
    )
    config["uderia_username"] = (
        overrides.get("username")
        or os.environ.get("UDERIA_USERNAME")
        or config.get("uderia_username")
    )
    config["uderia_password"] = (
        overrides.get("password")
        or os.environ.get("UDERIA_PASSWORD")
        or config.get("uderia_password")
    )

    if not config.get("uderia_username") or not config.get("uderia_password"):
        print("ERROR: Uderia credentials required. Provide via --username/--password, "
              "UDERIA_USERNAME/UDERIA_PASSWORD env vars, or config file.")
        sys.exit(1)

    # Validate required paths
    corpus_python = config.get("corpus_python")
    if not corpus_python or not Path(corpus_python).exists():
        print(f"ERROR: corpus_python not set or not found: {corpus_python}")
        print("Set it to the Python interpreter of your corpus_tools venv.")
        sys.exit(1)

    for key in ("corpcontent_dir", "corpus_tools_dir", "corpus_output_dir"):
        path = config.get(key)
        if not path or not Path(path).exists():
            print(f"ERROR: {key} not set or not found: {path}")
            sys.exit(1)

    return config


# ── Phase 1: Change Detection ────────────────────────────────────────────────

def detect_changes(config: dict) -> tuple[dict[str, bool], bool]:
    """Detect which categories have new/modified source files.

    Compares the newest source file mtime in each CorpContent/{category}/
    against the mtime of the corresponding {category}_Corpus.json.

    Returns:
        (changes, has_deletions) where changes is {category: needs_rebuild}.
    """
    corpcontent = Path(config["corpcontent_dir"])
    corpus_out = Path(config["corpus_output_dir"])
    categories = config["categories"]

    changes = {}
    for category in categories:
        content_dir = corpcontent / category
        corpus_file = corpus_out / f"{category}_Corpus.json"

        if not content_dir.exists():
            logger.warning(f"Category dir missing: {content_dir}")
            changes[category] = False
            continue

        # If corpus file doesn't exist yet, category needs processing
        if not corpus_file.exists():
            logger.info(f"  {category}: corpus JSON missing — needs build")
            changes[category] = True
            continue

        corpus_mtime = corpus_file.stat().st_mtime

        # Check if any source file is newer than the corpus JSON
        needs_rebuild = False
        newest_file = None
        for f in content_dir.iterdir():
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
                if f.stat().st_mtime > corpus_mtime:
                    needs_rebuild = True
                    newest_file = f.name
                    break

        if needs_rebuild:
            logger.info(f"  {category}: changed (e.g. {newest_file})")
        changes[category] = needs_rebuild

    # Check _DeleteFromCorpus for pending deletions
    delete_dir = corpcontent / "_DeleteFromCorpus"
    has_deletions = False
    if delete_dir.exists():
        has_deletions = any(
            f.is_file() and not f.name.startswith(".")
            for f in delete_dir.iterdir()
        )
        if has_deletions:
            logger.info("  Pending deletions in _DeleteFromCorpus/")

    return changes, has_deletions


# ── Phase 2: Content Processing ──────────────────────────────────────────────

def process_content(
    config: dict,
    changes: dict[str, bool],
    has_deletions: bool,
) -> list[str]:
    """Run corpus_tools to process changed categories.

    Returns list of categories that were successfully processed.
    """
    corpus_tools = Path(config["corpus_tools_dir"])
    corpus_python = config["corpus_python"]
    corpcontent = config["corpcontent_dir"]
    corpus_output = config["corpus_output_dir"]
    processed = []

    # Step 1: Handle pending deletions
    if has_deletions:
        logger.info("Running PurgeContent for pending deletions...")
        result = subprocess.run(
            [corpus_python, str(corpus_tools / "PurgeContent.py"),
             corpcontent, "--corpus-dir", corpus_output],
            capture_output=True, text=True, timeout=120,
            cwd=str(corpus_tools.parent),
        )
        if result.returncode != 0:
            logger.error(f"PurgeContent failed: {result.stderr}")
        else:
            logger.info("PurgeContent completed")

    # Step 2: Process each changed category
    categories_to_process = [c for c, changed in changes.items() if changed]
    for category in categories_to_process:
        source_dir = str(Path(corpcontent) / category)
        logger.info(f"Processing {category}...")

        try:
            result = subprocess.run(
                [corpus_python, str(corpus_tools / "CreateContent.py"),
                 source_dir, "--output-dir", corpus_output],
                capture_output=True, text=True,
                timeout=CONTENT_TIMEOUT,
                cwd=str(corpus_tools.parent),
            )
            if result.returncode != 0:
                logger.error(f"CreateContent failed for {category}: {result.stderr}")
                continue
            logger.info(f"  {category} processed successfully")
            processed.append(category)
        except subprocess.TimeoutExpired:
            logger.error(f"CreateContent timed out for {category} ({CONTENT_TIMEOUT}s)")
            continue

    # Step 3: Combine all corpora (always run if anything was processed)
    if processed or has_deletions:
        logger.info("Combining all corpora...")
        result = subprocess.run(
            [corpus_python, str(corpus_tools / "CombineCorpus.py"),
             "--corpus-dir", corpus_output],
            capture_output=True, text=True, timeout=120,
            cwd=str(corpus_tools.parent),
        )
        if result.returncode != 0:
            logger.error(f"CombineCorpus failed: {result.stderr}")

    return processed


# ── Phase 5: Build Agent Pack ─────────────────────────────────────────────────

def build_agentpack(config: dict) -> Path:
    """Build vat.agentpack from corpus JSON files.

    Returns path to the generated .agentpack file.
    """
    corpus_output = config["corpus_output_dir"]
    output_dir = str(SCRIPT_DIR / "import_output")
    agentpack_path = Path(output_dir) / "vat.agentpack"

    # Preserve previous agentpack as backup
    if agentpack_path.exists():
        backup = agentpack_path.with_suffix(".agentpack.prev")
        shutil.copy2(agentpack_path, backup)
        logger.info(f"Backed up previous agentpack to {backup.name}")

    logger.info("Building vat.agentpack...")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "build_agentpack.py"),
         "--corpus-dir", corpus_output,
         "--output-dir", output_dir],
        capture_output=True, text=True,
        timeout=600,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"build_agentpack.py failed:\n{result.stderr}\n{result.stdout}")

    if not agentpack_path.exists():
        raise RuntimeError(f"build_agentpack.py did not produce {agentpack_path}")

    size_mb = agentpack_path.stat().st_size / (1024 * 1024)
    logger.info(f"Built vat.agentpack ({size_mb:.1f} MB)")
    return agentpack_path


# ── Phase 6: Import to Uderia ─────────────────────────────────────────────────

def authenticate(config: dict) -> str:
    """Authenticate with Uderia and return JWT token."""
    resp = requests.post(
        f"{config['uderia_base_url']}/api/v1/auth/login",
        json={
            "username": config["uderia_username"],
            "password": config["uderia_password"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def update_uderia(config: dict, agentpack_path: Path) -> dict:
    """Import agentpack into Uderia via REST API.

    Uses multipart file upload to support remote servers.
    Uses conflict_strategy="replace" for atomic update of existing VAT data.
    Retries on connection errors (server may be starting up).
    """
    last_error = None
    for attempt in range(1, IMPORT_RETRY_COUNT + 1):
        try:
            token = authenticate(config)

            size_mb = agentpack_path.stat().st_size / (1024 * 1024)
            logger.info(
                f"Uploading agentpack ({size_mb:.1f} MB, "
                f"attempt {attempt}/{IMPORT_RETRY_COUNT})..."
            )
            with open(agentpack_path, "rb") as f:
                resp = requests.post(
                    f"{config['uderia_base_url']}/api/v1/agent-packs/import",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("vat.agentpack", f, "application/zip")},
                    data={"conflict_strategy": "replace"},
                    timeout=600,
                )

            if resp.status_code == 200:
                result = resp.json()
                logger.info(f"Import successful: {result.get('message', 'OK')}")
                return result
            else:
                raise RuntimeError(
                    f"Import returned {resp.status_code}: {resp.text}"
                )

        except requests.ConnectionError as e:
            last_error = e
            logger.warning(
                f"Cannot connect to Uderia (attempt {attempt}/{IMPORT_RETRY_COUNT}): {e}"
            )
            if attempt < IMPORT_RETRY_COUNT:
                logger.info(f"Retrying in {IMPORT_RETRY_DELAY}s...")
                time.sleep(IMPORT_RETRY_DELAY)

    raise RuntimeError(
        f"Failed to connect to Uderia after {IMPORT_RETRY_COUNT} attempts: {last_error}"
    )


# ── Phase 7: Verification ────────────────────────────────────────────────────

def verify_update(config: dict, import_result: dict) -> None:
    """Verify that all VAT profiles and collections exist after import."""
    token = authenticate(config)

    # Check profiles
    resp = requests.get(
        f"{config['uderia_base_url']}/api/v1/profiles",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    profiles = resp.json()

    # Profiles may be in a list or under a key
    profile_list = profiles if isinstance(profiles, list) else profiles.get("profiles", [])
    found_tags = {p.get("tag") for p in profile_list if p.get("tag") in ALL_VAT_TAGS}
    missing = ALL_VAT_TAGS - found_tags

    if missing:
        logger.warning(f"Verification: missing profiles: {missing}")
    else:
        logger.info(f"Verification: all {len(ALL_VAT_TAGS)} VAT profiles present")

    # Check installation record
    installation_id = import_result.get("installation_id")
    if installation_id:
        resp = requests.get(
            f"{config['uderia_base_url']}/api/v1/agent-packs/{installation_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code == 200:
            details = resp.json()
            resources = details.get("resources", [])
            collections = [r for r in resources if r.get("resource_type") == "collection"]
            profiles = [r for r in resources if r.get("resource_type") == "profile"]
            logger.info(
                f"Verification: installation {installation_id} — "
                f"{len(profiles)} profiles, {len(collections)} collections"
            )


# ── Logging ──────────────────────────────────────────────────────────────────

def append_run_log(entry: dict) -> None:
    """Append a structured JSON line to pipeline_runs.log."""
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    config: dict,
    *,
    force: bool = False,
    skip_content: bool = False,
    dry_run: bool = False,
    trigger: str = "manual",
) -> dict:
    """Execute the full pipeline.

    Returns a log entry dict with status and details.
    """
    start = time.time()
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
    }

    try:
        # Phase 1: Detect changes
        logger.info("=" * 60)
        logger.info("Phase 1: Detecting changes")
        logger.info("=" * 60)

        if force:
            logger.info("Force mode: rebuilding all categories")
            changes = {c: True for c in config["categories"]}
            has_deletions = False
        else:
            changes, has_deletions = detect_changes(config)

        changed_categories = [c for c, v in changes.items() if v]
        log_entry["categories_changed"] = changed_categories
        log_entry["has_deletions"] = has_deletions

        if not changed_categories and not has_deletions:
            logger.info("No changes detected.")
            log_entry["status"] = "no_changes"
            return log_entry

        logger.info(
            f"Changes detected: {len(changed_categories)} categories"
            + (", pending deletions" if has_deletions else "")
        )

        if dry_run:
            logger.info("Dry run — stopping here.")
            log_entry["status"] = "dry_run"
            return log_entry

        # Phase 2: Content processing
        if not skip_content:
            logger.info("")
            logger.info("=" * 60)
            logger.info("Phase 2: Processing content")
            logger.info("=" * 60)
            processed = process_content(config, changes, has_deletions)
            log_entry["categories_processed"] = processed

            if not processed and not has_deletions:
                logger.error("No categories processed successfully. Aborting.")
                log_entry["status"] = "failed"
                log_entry["error"] = "Content processing failed for all categories"
                return log_entry
        else:
            logger.info("Skipping content processing (--skip-content)")
            log_entry["categories_processed"] = []

        # Phase 3 & 4: FAISS cache rebuild and VAT deploy (RETIRED)
        # These phases are no longer needed — Uderia's ChromaDB replaces FAISS,
        # and the VAT frontend now uses Uderia as its backend.
        logger.info("")
        logger.info("Phases 3-4: Skipped (FAISS rebuild + VAT deploy retired — Uderia is the backend)")

        # Phase 5: Build agentpack
        logger.info("")
        logger.info("=" * 60)
        logger.info("Phase 5: Building agent pack")
        logger.info("=" * 60)
        agentpack_path = build_agentpack(config)
        log_entry["agentpack_size_mb"] = round(
            agentpack_path.stat().st_size / (1024 * 1024), 1
        )

        # Phase 6: Import to Uderia
        logger.info("")
        logger.info("=" * 60)
        logger.info("Phase 6: Importing to Uderia")
        logger.info("=" * 60)
        import_result = update_uderia(config, agentpack_path)
        log_entry["installation_id"] = import_result.get("installation_id")

        # Phase 7: Verify
        logger.info("")
        logger.info("=" * 60)
        logger.info("Phase 7: Verifying")
        logger.info("=" * 60)
        verify_update(config, import_result)

        log_entry["status"] = "success"
        logger.info("")
        logger.info("Pipeline completed successfully.")

    except Exception as e:
        log_entry["status"] = "failed"
        log_entry["error"] = str(e)
        logger.error(f"Pipeline failed: {e}", exc_info=True)

    finally:
        log_entry["duration_seconds"] = round(time.time() - start, 1)
        append_run_log(log_entry)

    return log_entry


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="VAT Agent Pack Pipeline — automated content-to-agentpack workflow"
    )
    parser.add_argument(
        "--config", type=str, default=str(DEFAULT_CONFIG_PATH),
        help="Path to pipeline_config.json",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force full rebuild of all categories (ignore change detection)",
    )
    parser.add_argument(
        "--skip-content", action="store_true",
        help="Skip corpus processing, rebuild agentpack from existing corpus JSONs",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Detect changes only, don't process anything",
    )
    parser.add_argument(
        "--if-changed", action="store_true",
        help="Cron mode: exit 0 immediately if no changes, otherwise run pipeline",
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Polling mode: run pipeline in a loop",
    )
    parser.add_argument(
        "--interval", type=int, default=3600,
        help="Polling interval in seconds (default: 3600)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--base-url", type=str, default=None,
        help="Uderia server URL (overrides config/env)",
    )
    parser.add_argument(
        "--username", type=str, default=None,
        help="Uderia username (overrides config/env)",
    )
    parser.add_argument(
        "--password", type=str, default=None,
        help="Uderia password (overrides config/env)",
    )
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    cli_overrides = {
        "base_url": args.base_url,
        "username": args.username,
        "password": args.password,
    }
    config = load_config(Path(args.config), cli_overrides=cli_overrides)

    if args.watch:
        logger.info(f"Watch mode: polling every {args.interval}s")
        while True:
            result = run_pipeline(config, force=args.force, trigger="watch")
            status = result.get("status", "unknown")
            if status == "no_changes":
                logger.info(f"No changes. Next check in {args.interval}s.")
            elif status == "success":
                logger.info(f"Pipeline succeeded. Next check in {args.interval}s.")
            else:
                logger.error(f"Pipeline finished with status: {status}")
            time.sleep(args.interval)

    elif args.if_changed:
        changes, has_deletions = detect_changes(config)
        if not any(changes.values()) and not has_deletions:
            # No changes — silent exit for cron
            sys.exit(0)
        result = run_pipeline(config, trigger="cron")
        sys.exit(0 if result.get("status") == "success" else 1)

    else:
        result = run_pipeline(
            config,
            force=args.force,
            skip_content=args.skip_content,
            dry_run=args.dry_run,
            trigger="manual",
        )
        sys.exit(0 if result.get("status") in ("success", "no_changes", "dry_run") else 1)


if __name__ == "__main__":
    main()
