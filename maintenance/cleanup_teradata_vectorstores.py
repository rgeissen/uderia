#!/usr/bin/env python3
"""
Clean up orphaned VectorStore objects on Teradata.

Compares VectorStore objects on the remote Teradata server against the local
collection database and removes any that don't have a matching local record.

Usage:
    python maintenance/cleanup_teradata_vectorstores.py              # Dry run (list only)
    python maintenance/cleanup_teradata_vectorstores.py --force      # Delete orphans
    python maintenance/cleanup_teradata_vectorstores.py --user admin # Specify username
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def resolve_teradata_config(username: str) -> dict:
    """Resolve Teradata connection config + decrypted credentials for a user."""
    from trusted_data_agent.auth.database import get_db_session
    from trusted_data_agent.auth.models import User
    from trusted_data_agent.core.config_manager import get_config_manager
    from trusted_data_agent.auth.encryption import decrypt_credentials

    # Find user UUID
    with get_db_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            raise RuntimeError(f"User '{username}' not found in database")
        user_uuid = user.id

    logger.info(f"Resolved user '{username}' -> {user_uuid}")

    # Get vector store configurations
    config_manager = get_config_manager()
    vs_configs = config_manager.get_vector_store_configurations(user_uuid)
    td_config = next(
        (c for c in vs_configs if c.get("backend_type") == "teradata"),
        None,
    )
    if not td_config:
        raise RuntimeError(f"No Teradata vector store configuration found for user '{username}'")

    vs_config_id = td_config["id"]
    backend_config = td_config.get("backend_config", {})
    if isinstance(backend_config, str):
        backend_config = json.loads(backend_config)

    # Decrypt credentials
    credentials = decrypt_credentials(user_uuid, f"vectorstore_{vs_config_id}")
    if credentials:
        backend_config = {**backend_config, **credentials}

    logger.info(f"Using Teradata config '{td_config['name']}' (host: {backend_config.get('host')})")
    return backend_config


def connect_teradata(config: dict):
    """Establish Teradata SQL + REST API connections."""
    from teradataml import create_context
    from teradatagenai import set_auth_token

    # SQL context
    ctx_kwargs = {"host": config["host"], "username": config["username"]}
    if config.get("password"):
        ctx_kwargs["password"] = config["password"]
    if config.get("database"):
        ctx_kwargs["database"] = config["database"]
    create_context(**ctx_kwargs)
    logger.info("SQL context established")

    # REST API auth
    if config.get("pat_token"):
        base_url = config.get("base_url", "")
        if base_url.endswith("/open-analytics"):
            base_url = base_url[: -len("/open-analytics")]

        pat_kwargs = {"base_url": base_url, "pat_token": config["pat_token"]}

        # Handle PEM — file path or inline content
        pem_file = config.get("pem_file", "")
        pem_content = config.get("pem_content", "")
        pem_key_name = config.get("pem_key_name", "")

        if pem_content and not pem_file:
            import tempfile, os

            if not pem_key_name:
                pem_key_name = config.get("username", "key")
            tmpdir = tempfile.mkdtemp(prefix="tda_vs_cleanup_")
            pem_path = os.path.join(tmpdir, f"{pem_key_name}.pem")
            with open(pem_path, "w") as f:
                content = pem_content
                if not content.endswith("\n"):
                    content += "\n"
                f.write(content)
            pem_file = pem_path

        if pem_file:
            pat_kwargs["pem_file"] = pem_file

        set_auth_token(**pat_kwargs)
        logger.info("REST API auth established (PAT + PEM)")
    else:
        set_auth_token(
            base_url=config.get("base_url", ""),
            username=config["username"],
            password=config.get("password", ""),
        )
        logger.info("REST API auth established (Basic)")


def list_remote_vectorstores() -> list:
    """List all VectorStore objects on the Teradata server."""
    from teradatagenai import VSManager

    try:
        result = VSManager.list()
    except Exception as exc:
        logger.error(f"Failed to list VectorStores: {exc}")
        return []

    # Convert teradataml DataFrame to list of dicts
    if hasattr(result, "to_pandas"):
        df = result.to_pandas()
        columns = df.columns.tolist()
        logger.info(f"VSManager.list() columns: {columns}")
        if len(df) > 0:
            logger.info(f"First row sample: {dict(df.iloc[0])}")
        return columns, [dict(row) for _, row in df.iterrows()]
    return [], []


def list_local_teradata_collections() -> set:
    """Get all collection_name values for Teradata-backed collections in local DB."""
    from trusted_data_agent.core.collection_db import get_collection_db

    collection_db = get_collection_db()
    all_collections = collection_db.get_all_collections()

    names = set()
    for coll in all_collections:
        if coll.get("backend_type") == "teradata":
            coll_name = coll.get("collection_name", "")
            if coll_name:
                names.add(coll_name.upper())
    return names


def drop_staging_tables(database: str, vs_name: str):
    """Drop staging and index tables associated with an orphaned VectorStore."""
    from teradataml import execute_sql

    safe = re.sub(r"[^A-Za-z0-9]", "_", vs_name)[:100].upper()
    staging = f"UDERIA_VS_{safe}"

    tables_to_drop = [f"{database}.{staging}"]

    for table in tables_to_drop:
        try:
            execute_sql(f"DROP TABLE {table}")
            logger.info(f"  Dropped staging table: {table}")
        except Exception:
            pass  # Table may not exist


def _find_column(columns: list, candidates: list) -> str:
    """Find the first matching column name (case-insensitive) from candidates."""
    col_upper = {c.upper(): c for c in columns}
    for candidate in candidates:
        if candidate.upper() in col_upper:
            return col_upper[candidate.upper()]
    return ""


def cleanup(force: bool, username: str, prefix: str = ""):
    """Main cleanup logic."""
    # 1. Connect
    config = resolve_teradata_config(username)
    connect_teradata(config)
    database = config.get("database", "")

    # 2. List remote VS objects
    columns, remote_stores = list_remote_vectorstores()
    if not remote_stores:
        logger.info("No VectorStore objects found on the Teradata server.")
        return

    # Discover name and status column names dynamically
    name_col = _find_column(columns, ["VS_NAME", "name", "NAME", "vs_name", "VectorStoreName", "vectorstore_name"])
    status_col = _find_column(columns, ["STATUS", "status", "State", "state", "VS_STATUS", "vs_status"])

    if not name_col:
        logger.warning(f"Could not identify name column. Available columns: {columns}")
        # Fall back to first column
        if columns:
            name_col = columns[0]
            logger.info(f"Using first column as name: '{name_col}'")
        else:
            logger.error("No columns found in VSManager.list() result")
            return

    if not status_col:
        logger.info(f"No status column found. Available columns: {columns}")

    logger.info(f"Using columns: name='{name_col}', status='{status_col or 'N/A'}'")

    logger.info(f"\nFound {len(remote_stores)} VectorStore(s) on server:")
    for vs in remote_stores:
        name = vs.get(name_col, "?")
        status = vs.get(status_col, "?") if status_col else "?"
        logger.info(f"  - {name} (status: {status})")

    # 3. List local Teradata collections
    local_names = list_local_teradata_collections()
    logger.info(f"\nFound {len(local_names)} Teradata collection(s) in local DB:")
    for name in sorted(local_names):
        logger.info(f"  - {name}")

    # 4. Identify orphans
    orphans = []
    kept = []
    for vs in remote_stores:
        name = vs.get(name_col, "")
        if not name:
            continue
        if name.upper() in local_names:
            kept.append(name)
        else:
            orphans.append(name)

    if not orphans:
        logger.info("\nNo orphaned VectorStores found. Everything is clean.")
        return

    logger.info(f"\nOrphaned VectorStores ({len(orphans)}):")
    for name in orphans:
        logger.info(f"  - {name}")

    if kept:
        logger.info(f"\nKept (matched local DB) ({len(kept)}):")
        for name in kept:
            logger.info(f"  - {name}")

    if not force:
        logger.info("\nDry run — no changes made. Use --force to delete orphans.")
        return

    # 5. Delete orphans
    from teradatagenai import VectorStore

    logger.info(f"\nDeleting {len(orphans)} orphaned VectorStore(s)...")
    deleted = 0
    failed = 0

    for name in orphans:
        try:
            vs = VectorStore(name)
            vs.destroy()
            logger.info(f"  Destroyed VectorStore: {name}")

            if database:
                drop_staging_tables(database, name)

            deleted += 1
        except Exception as exc:
            logger.error(f"  Failed to destroy {name}: {exc}")
            failed += 1

    logger.info(f"\nCleanup complete: {deleted} deleted, {failed} failed, {len(kept)} kept")


def main():
    parser = argparse.ArgumentParser(
        description="Clean up orphaned Teradata VectorStore objects"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actually delete orphans (default: dry run)",
    )
    parser.add_argument(
        "--user",
        default="admin",
        help="Username whose Teradata config to use (default: admin)",
    )
    parser.add_argument(
        "--prefix",
        default="tda_rag_coll_",
        help="Only clean VectorStores matching this prefix (default: tda_rag_coll_)",
    )
    args = parser.parse_args()

    cleanup(force=args.force, username=args.user, prefix=args.prefix)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)
