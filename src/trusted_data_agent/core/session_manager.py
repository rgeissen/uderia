# src/trusted_data_agent/core/session_manager.py
import uuid
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path # Use pathlib for better path handling
import shutil # For potential cleanup later if needed
import asyncio # For sending notifications asynchronously
import tempfile # For atomic file writes
import aiofiles # For async file I/O

import google.generativeai as genai
from trusted_data_agent.agent.prompts import PROVIDER_SYSTEM_PROMPTS
# --- MODIFICATION START: Import APP_CONFIG ---
from trusted_data_agent.core.config import APP_STATE, APP_CONFIG
from trusted_data_agent.core.utils import generate_session_id, get_project_root # Import generate_session_id and get_project_root
from trusted_data_agent.agent.rag_template_generator import RAGTemplateGenerator
# --- MODIFICATION END ---


# --- Define SESSIONS_DIR relative to project root ---
# Use the new get_project_root() function to find the correct project root
_PROJECT_ROOT = get_project_root()
SESSIONS_DIR = _PROJECT_ROOT / "tda_sessions"


app_logger = logging.getLogger("quart.app") # Use quart logger for consistency

def _initialize_sessions_dir():
    """Creates the main sessions directory if it doesn't exist."""
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        app_logger.debug(f"Session directory ensured at: {SESSIONS_DIR}")
    except OSError as e:
        app_logger.error(f"Could not create session directory '{SESSIONS_DIR}'. Session persistence will fail. Error: {e}", exc_info=True)
        raise # Re-raise to prevent startup if dir fails

# Call initialization when the module loads
_initialize_sessions_dir()

# --- Removed global _SESSIONS dictionary ---

# --- Notification Deduplication Cache ---
# Track last notification state per session to avoid spam
# Key: session_id, Value: dict with provider, model, profile_tag
_last_notification_state = {}

# --- Per-Session Write Lock ---
# Serializes load-modify-save cycles on a per-session basis to prevent:
# 1. File corruption from concurrent aiofiles writes (defense-in-depth; atomic writes are the primary guard)
# 2. Logical data loss where a stale load overwrites another writer's changes
# Key: session_id, Value: asyncio.Lock
_session_locks: dict[str, asyncio.Lock] = {}

def _get_session_lock(session_id: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock for a session to serialize file writes."""
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


from contextlib import asynccontextmanager

@asynccontextmanager
async def _session_transaction(user_uuid: str, session_id: str):
    """
    Context manager that serializes load-modify-save cycles for a session.

    Usage:
        async with _session_transaction(user_uuid, session_id) as session_data:
            if session_data is None:
                return  # Session not found
            session_data['field'] = new_value
            # Auto-saved on exit (only if session_data was found)

    The lock is held for the entire load-modify-save cycle, preventing concurrent
    writers from reading stale data and overwriting each other's changes.
    """
    lock = _get_session_lock(session_id)
    async with lock:
        session_data = await _load_session(user_uuid, session_id)
        yield session_data
        if session_data is not None:
            if not await _save_session(user_uuid, session_id, session_data):
                app_logger.error(f"Failed to save session {session_id} in transaction")


# --- File I/O Helper Functions ---

def _get_session_path(user_uuid: str, session_id: str) -> Path | None:
    """Constructs the session file path and performs basic validation."""
    if not user_uuid or not session_id:
        app_logger.error("Attempted to get session path with missing user_uuid or session_id.")
        return None
    # Basic sanitization (replace potentially harmful chars - adjust as needed)
    safe_user_uuid = "".join(c for c in user_uuid if c.isalnum() or c in ['-', '_'])
    safe_session_id = "".join(c for c in session_id if c.isalnum() or c in ['-', '_'])
    if safe_user_uuid != user_uuid or safe_session_id != session_id:
        app_logger.warning(f"Sanitized UUID/SessionID for path. Original: '{user_uuid}/{session_id}', Safe: '{safe_user_uuid}/{safe_session_id}'")

    return SESSIONS_DIR / safe_user_uuid / f"{safe_session_id}.json"

def _find_session_path(user_uuid: str, session_id: str) -> Path | None:
    """Finds the path to a session file, respecting SESSIONS_FILTER_BY_USER."""
    safe_session_id = "".join(c for c in session_id if c.isalnum() or c in ['-', '_'])

    if APP_CONFIG.SESSIONS_FILTER_BY_USER:
        # Look only in the specified user's directory
        path = _get_session_path(user_uuid, session_id)
        if path and path.is_file():
            return path
        return None
    else:
        # Search all user directories for the session file
        app_logger.debug(f"Session filtering is off. Searching for session '{safe_session_id}' in all user directories.")
        for user_dir in SESSIONS_DIR.iterdir():
            if user_dir.is_dir():
                potential_path = user_dir / f"{safe_session_id}.json"
                if potential_path.is_file():
                    app_logger.debug(f"Found session '{safe_session_id}' in directory '{user_dir}'.")
                    return potential_path
        return None

async def _load_session(user_uuid: str, session_id: str) -> dict | None:
    """Loads session data from a file asynchronously."""
    session_path = _find_session_path(user_uuid, session_id)
    if not session_path:
        app_logger.warning(f"Session file not found for session_id: {session_id}")
        return None

    app_logger.debug(f"Attempting to load session from: {session_path}")
    try:
        # The check is technically redundant if _find_session_path finds something, but good for safety
        if session_path.is_file():
            async with aiofiles.open(session_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
                app_logger.debug(f"Successfully loaded session '{session_id}' (owned by {data.get('user_uuid')}) for requesting user '{user_uuid}'.")
                return data
        else:
            app_logger.warning(f"Session file not found at: {session_path}")
            return None
    except (json.JSONDecodeError, OSError) as e:
        app_logger.error(f"Error loading session file '{session_path}': {e}", exc_info=True)
        return None # Return None on error

async def _save_session(user_uuid: str, session_id: str, session_data: dict):
    """Saves session data to a file asynchronously, creating directories if needed."""
    session_data['last_updated'] = datetime.now().isoformat()
    session_path = _get_session_path(user_uuid, session_id)
    if not session_path:
        app_logger.error(f"Cannot save session '{session_id}' for user '{user_uuid}': Invalid path.")
        return False # Indicate failure
    app_logger.debug(f"Attempting to save session to: {session_path}")
    try:
        # Ensure the user's directory exists
        session_path.parent.mkdir(parents=True, exist_ok=True)
        if not session_path.parent.exists():
             app_logger.warning(f"User session directory was just created (or failed silently): {session_path.parent}")

        # Atomic write: write to temp file, then rename (os.replace is atomic on POSIX).
        # This prevents file corruption when concurrent async tasks write simultaneously.
        json_content = json.dumps(session_data, indent=2)
        temp_fd, temp_path = tempfile.mkstemp(
            dir=str(session_path.parent),
            suffix='.tmp',
            prefix='.session_'
        )
        try:
            os.close(temp_fd)  # Close fd; we use aiofiles for async write
            async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                await f.write(json_content)
            os.replace(temp_path, str(session_path))  # Atomic on POSIX
        except BaseException:
            # Clean up temp file on any error
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
        app_logger.debug(f"Successfully saved session '{session_id}' for user '{user_uuid}'.")

        # --- MODIFICATION START: Send session_model_update notification (with deduplication) ---
        notification_queues = APP_STATE.get("notification_queues", {}).get(user_uuid, set())
        if notification_queues:
            # Check if notification state has changed
            # Include profile_tags_used as a tuple for comparison (arrays aren't directly comparable)
            profile_tags_used = session_data.get("profile_tags_used", [])
            current_state = {
                "provider": session_data.get("provider"),
                "model": session_data.get("model"),
                "profile_tag": session_data.get("profile_tag"),
                "profile_tags_used": tuple(profile_tags_used) if profile_tags_used else (),
            }
            last_state = _last_notification_state.get(session_id)

            # Only send notification if state changed or this is the first notification
            if last_state != current_state:
                notification_payload = {
                    "session_id": session_id,
                    "models_used": session_data.get("models_used", []),
                    "profile_tags_used": session_data.get("profile_tags_used", []),
                    "last_updated": session_data.get("last_updated"),
                    "provider": current_state["provider"],
                    "model": current_state["model"],
                    "name": session_data.get("name", "Unnamed Session"),
                }
                app_logger.debug(f"_save_session sending notification for session {session_id}: provider={notification_payload['provider']}, model={notification_payload['model']}, profile_tags_used={notification_payload['profile_tags_used']} (state changed)")
                notification = {
                    "type": "session_model_update",
                    "payload": notification_payload
                }
                for queue in notification_queues:
                    asyncio.create_task(queue.put(notification))
                
                # Update cache
                _last_notification_state[session_id] = current_state
            else:
                app_logger.debug(f"_save_session skipping notification for session {session_id}: state unchanged")
        # --- MODIFICATION END ---

        return True # Indicate success
    except OSError as e:
        app_logger.error(f"Error saving session file '{session_path}': {e}", exc_info=True)
        return False # Indicate failure


# --- Public Session Management Functions ---

async def create_session(user_uuid: str, provider: str, llm_instance: any, charting_intensity: str, system_prompt_template: str | None = None, profile_tag: str | None = None, profile_id: str | None = None, is_temporary: bool = False, temporary_purpose: str | None = None, genie_parent_session_id: str | None = None, genie_slave_profile_id: str | None = None, genie_sequence_number: int | None = None) -> str:
    session_id = generate_session_id()
    app_logger.info(f"Attempting to create session '{session_id}' for user '{user_uuid}' (temporary: {is_temporary}).")

    # Note: chat_object cannot be directly serialized to JSON.
    # We will store history as a plain list.
    chat_history_for_file = []
    if provider == "Google":
        # Keep initial prompt for Google compatibility if needed later, but don't store the live object.
        initial_history_google = [
            {"role": "user", "parts": [{"text": "You are a helpful assistant."}]},
            {"role": "model", "parts": [{"text": "Understood."}]}
        ]
        # Store this initial history in the file version
        chat_history_for_file = [{'role': m['role'], 'content': m['parts'][0]['text']} for m in initial_history_google]

    session_data = {
        "id": session_id, # Store ID within the data itself
        "user_uuid": user_uuid, # Store user UUID for potential later use/verification
        "system_prompt_template": system_prompt_template,
        "charting_intensity": charting_intensity,
        "provider": provider, # --- Store the provider used for this session (for backwards compatibility)
        "model": APP_CONFIG.CURRENT_MODEL, # --- Store the model used for this session (for backwards compatibility)
        "profile_tag": profile_tag, # --- Store the profile tag used for this session
        "profile_id": profile_id, # --- Store the profile ID used for this session (for badge/color info)
        "profile_tags_used": [], # --- Populated on first query execution, not on session creation
        "models_used": [], # --- Keep for backwards compatibility
        "session_history": [], # UI history (messages added via add_message_to_histories)
        "chat_object": chat_history_for_file, # Store serializable history for LLM context
        "name": "New Chat",
        "created_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
        "input_tokens": 0,
        "output_tokens": 0,
        # --- MODIFICATION START: Ensure workflow_history list exists on creation ---
        "last_turn_data": {"workflow_history": []},
        # --- MODIFICATION END ---
        "full_context_sent": False,
        "license_info": APP_STATE.get("license_info"), # Store license info at creation time
        "is_temporary": is_temporary, # Mark if this is a temporary/utility session
        "temporary_purpose": temporary_purpose, # Optional description of the temporary session purpose
        # --- GENIE PROFILE METADATA ---
        "genie_metadata": {
            "is_genie_slave": genie_parent_session_id is not None,
            "parent_session_id": genie_parent_session_id,
            "slave_profile_id": genie_slave_profile_id,
            "slave_sequence_number": genie_sequence_number or 0
        }
    }

    if await _save_session(user_uuid, session_id, session_data):
        app_logger.info(f"Successfully created and saved session '{session_id}' for user '{user_uuid}'.")
        
        # --- CONSUMPTION TRACKING START ---
        # Increment session count in consumption database (only if truly new)
        try:
            from trusted_data_agent.auth.database import get_db_session
            from trusted_data_agent.auth.consumption_manager import ConsumptionManager
            
            with get_db_session() as db_session:
                manager = ConsumptionManager(db_session)
                manager.increment_session_count(user_uuid, session_id, is_new_session=True)
                app_logger.debug(f"Updated session count for user {user_uuid}, session {session_id}")
        except Exception as e:
            # Non-critical: File storage is source of truth, DB is performance cache
            app_logger.warning(f"Failed to update session count for user {user_uuid}: {e}")
        # --- CONSUMPTION TRACKING END ---
        
        return session_id
    else:
        app_logger.error(f"Failed to save newly created session '{session_id}' for user '{user_uuid}'.")
        raise IOError(f"Failed to save session file for session {session_id}")


async def get_session(user_uuid: str, session_id: str) -> dict | None:
    app_logger.debug(f"Getting session '{session_id}' for user '{user_uuid}'.")
    session_data = await _load_session(user_uuid, session_id)
    if session_data:
        history_modified = False
        # --- MODIFICATION START: Update backfill logic for turn numbers ---
        if "session_history" in session_data and session_data["session_history"]:
            if session_data["session_history"] and "turn_number" not in session_data["session_history"][0]:
                app_logger.info(f"Session {session_id} history is outdated. Adding turn numbers.")
                history_modified = True
                turn_counter = 0
                for msg in session_data["session_history"]:
                    if msg.get("role") == "user":
                        turn_counter += 1
                    msg["turn_number"] = turn_counter

        if "chat_object" in session_data and session_data["chat_object"]:
            if session_data["chat_object"] and "turn_number" not in session_data["chat_object"][0]:
                if not history_modified:
                    app_logger.info(f"Session {session_id} chat_object is outdated. Adding turn numbers.")
                history_modified = True
                turn_counter = 0
                # Skip the initial system message which doesn't have a turn
                for i, msg in enumerate(session_data["chat_object"]):
                    # The first two messages are the system prompt and should not be part of a turn
                    if i < 2:
                        msg["turn_number"] = 0
                        continue
                    if msg.get("role") == "user":
                        turn_counter += 1
                    msg["turn_number"] = turn_counter

        if history_modified:
            app_logger.info(f"Saving session {session_id} after migrating to include turn numbers.")
            await _save_session(user_uuid, session_id, session_data)

        # Enrich genie_metadata with nesting_level and slave_profile_tag from database
        genie_metadata = session_data.get("genie_metadata", {})
        if genie_metadata.get("is_genie_slave"):
            parent_link = await get_genie_parent_session(session_id, user_uuid)
            if parent_link:
                nesting_level = parent_link.get("nesting_level", 0)
                slave_profile_tag = parent_link.get("slave_profile_tag")
                genie_metadata["nesting_level"] = nesting_level
                genie_metadata["slave_profile_tag"] = slave_profile_tag
                session_data["genie_metadata"] = genie_metadata
                app_logger.debug(f"Enriched session {session_id} with nesting_level={nesting_level}, slave_profile_tag={slave_profile_tag}")

    return session_data

async def get_all_sessions(user_uuid: str, limit: int = None, offset: int = 0, include_archived: bool = False) -> dict:
    """
    Get all sessions for a user with optional pagination.

    Args:
        user_uuid: The user's UUID
        limit: Maximum number of sessions to return (None = all sessions)
        offset: Number of sessions to skip (for pagination)
        include_archived: Whether to include archived sessions (default: False)

    Returns:
        dict with keys:
            - sessions: list of session summaries
            - total_count: total number of sessions (before pagination)
            - has_more: boolean indicating if more sessions exist
    """
    from trusted_data_agent.core.config import APP_CONFIG

    app_logger.debug(f"Getting all sessions for user '{user_uuid}'. Filter by user: {APP_CONFIG.SESSIONS_FILTER_BY_USER}, limit={limit}, offset={offset}")
    session_summaries = []

    # Determine which directories to scan based on filter setting
    if APP_CONFIG.SESSIONS_FILTER_BY_USER:
        # User-specific mode: scan only the user's directory
        user_session_dir = SESSIONS_DIR / "".join(c for c in user_uuid if c.isalnum() or c in ['-', '_'])
        app_logger.debug(f"Scanning user-specific directory: {user_session_dir}")
        if not user_session_dir.is_dir():
            # Create the directory if it doesn't exist (first time for this user)
            try:
                user_session_dir.mkdir(parents=True, exist_ok=True)
                app_logger.info(f"Created user session directory: {user_session_dir}")
            except OSError as e:
                app_logger.error(f"Failed to create user session directory: {user_session_dir}. Error: {e}")
                return {"sessions": [], "total_count": 0, "has_more": False}
        scan_dirs = [user_session_dir]
    else:
        # All users mode: scan all subdirectories
        app_logger.debug(f"Scanning all user directories in: {SESSIONS_DIR}")
        if not SESSIONS_DIR.is_dir():
            app_logger.warning(f"Sessions directory not found: {SESSIONS_DIR}. Returning empty list.")
            return {"sessions": [], "total_count": 0, "has_more": False}
        scan_dirs = [d for d in SESSIONS_DIR.iterdir() if d.is_dir()]

    # Scan all determined directories (recursively to include child Genie sessions)
    # First pass: collect all session summaries WITHOUT genie metadata enrichment
    for session_dir in scan_dirs:
        for session_file in session_dir.glob("**/*.json"):
            app_logger.debug(f"Found potential session file: {session_file.name}")
            try:
                async with aiofiles.open(session_file, 'r', encoding='utf-8') as f:
                    # Load only necessary fields for summary to improve performance
                    content = await f.read()
                    data = json.loads(content)

                    genie_metadata = data.get("genie_metadata", {})

                    summary = {
                        "id": data.get("id", session_file.stem),
                        "name": data.get("name", "Unnamed Session"),
                        "created_at": data.get("created_at", "Unknown"),
                        "models_used": data.get("models_used", []),
                        "profile_tags_used": data.get("profile_tags_used", []),
                        "last_updated": data.get("last_updated", data.get("created_at", "Unknown")),
                        "archived": data.get("archived", False),
                        "archived_at": data.get("archived_at"),
                        # Additional fields for UI display
                        "profile_tag": data.get("profile_tag"),
                        "profile_id": data.get("profile_id"),
                        "is_temporary": data.get("is_temporary", False),
                        "temporary_purpose": data.get("temporary_purpose"),
                        "genie_metadata": genie_metadata
                    }
                    app_logger.debug(f"Loaded summary for {session_file.name}: models_used={summary['models_used']}, profile_tags_used={summary['profile_tags_used']}")
                    session_summaries.append(summary)
                    app_logger.debug(f"Successfully loaded summary for {session_file.name}.")
            except (json.JSONDecodeError, OSError, KeyError) as e:
                app_logger.error(f"Error loading summary from session file '{session_file}': {e}", exc_info=False) # Keep log concise
                # Optionally add a placeholder or skip corrupted files
                session_summaries.append({
                     "id": session_file.stem,
                     "name": f"Error Loading ({session_file.stem})",
                     "created_at": "Unknown"
                })

    # --- BATCH GENIE METADATA ENRICHMENT ---
    # Collect all slave session IDs that need metadata enrichment
    slave_session_ids = [
        s["id"] for s in session_summaries
        if s.get("genie_metadata", {}).get("is_genie_slave")
    ]

    # Batch query for all slave session metadata in a single database call
    if slave_session_ids:
        try:
            import sqlite3
            from trusted_data_agent.core.utils import get_project_root

            db_path = str(get_project_root() / "tda_auth.db")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Single query for all slave sessions
            placeholders = ','.join(['?'] * len(slave_session_ids))
            cursor.execute(f"""
                SELECT slave_session_id, nesting_level, slave_profile_tag
                FROM genie_session_links
                WHERE slave_session_id IN ({placeholders})
            """, slave_session_ids)

            rows = cursor.fetchall()

            # Build lookup map
            metadata_map = {row['slave_session_id']: dict(row) for row in rows}

            # Apply metadata to sessions, auto-repair orphaned slaves
            repaired_count = 0
            for session in session_summaries:
                session_id = session.get("id")
                if session_id in metadata_map:
                    genie_data = metadata_map[session_id]
                    session["genie_metadata"]["nesting_level"] = genie_data.get("nesting_level", 0)
                    session["genie_metadata"]["slave_profile_tag"] = genie_data.get("slave_profile_tag")
                elif session.get("genie_metadata", {}).get("is_genie_slave"):
                    # Auto-repair: insert missing link from session file data
                    genie_meta = session.get("genie_metadata", {})
                    parent_id = genie_meta.get("parent_session_id")
                    slave_profile_id = genie_meta.get("slave_profile_id", "")
                    slave_profile_tag = genie_meta.get("slave_profile_tag", "")
                    sequence_num = genie_meta.get("slave_sequence_number", 0)

                    if parent_id:
                        try:
                            cursor.execute("""
                                INSERT OR IGNORE INTO genie_session_links
                                (parent_session_id, slave_session_id, slave_profile_id,
                                 slave_profile_tag, user_uuid, execution_order, nesting_level)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (parent_id, session_id, slave_profile_id,
                                  slave_profile_tag, user_uuid, sequence_num, 0))
                            conn.commit()
                            session["genie_metadata"]["nesting_level"] = 0
                            repaired_count += 1
                            app_logger.info(f"Auto-repaired genie session link: {parent_id} -> {session_id}")
                        except Exception as repair_err:
                            app_logger.debug(f"Could not auto-repair genie link for {session_id}: {repair_err}")
                    else:
                        app_logger.debug(f"Orphaned genie slave session {session_id} has no parent_session_id")

            conn.close()

            if repaired_count > 0:
                app_logger.info(f"Auto-repaired {repaired_count} orphaned genie session links")
            app_logger.debug(f"Batch enriched {len(metadata_map)} genie slave sessions")
        except Exception as e:
            app_logger.error(f"Failed to batch enrich genie metadata: {e}", exc_info=True)
    # --- END BATCH GENIE METADATA ENRICHMENT ---


    # Filter out template generation sessions
    app_logger.debug(f"[Session Scan Complete] Found {len(session_summaries)} total sessions before filtering")
    for session in session_summaries:
        session_id = session.get("id", "unknown")[:12]
        is_slave = session.get("genie_metadata", {}).get("is_genie_slave", False)
        nesting_level = session.get("genie_metadata", {}).get("nesting_level", "N/A")
        app_logger.debug(f"[Session Scan] {session_id}... (slave={is_slave}, level={nesting_level})")

    session_summaries = [
        session for session in session_summaries
        if session.get("id") != RAGTemplateGenerator.TEMPLATE_SESSION_ID
    ]

    app_logger.debug(f"[After Template Filter] {len(session_summaries)} sessions remain")

    # Filter archived sessions unless explicitly requested
    if not include_archived:
        session_summaries = [
            session for session in session_summaries
            if not session.get("archived", False)
        ]
        app_logger.debug(f"[After Archived Filter] {len(session_summaries)} active sessions remain")
    else:
        app_logger.debug(f"[Include Archived] Keeping all {len(session_summaries)} sessions (including archived)")

    # Sort sessions with genie child sessions appearing directly after their parent
    # Build a lookup map for quick access
    session_by_id = {s.get("id"): s for s in session_summaries}

    # Separate parent sessions from child sessions
    parent_sessions = []
    slave_sessions_by_parent = {}  # parent_id -> list of slaves

    app_logger.debug(f"[Session Hierarchy] Processing {len(session_summaries)} total sessions")
    for session in session_summaries:
        genie_metadata = session.get("genie_metadata", {})
        parent_id = genie_metadata.get("parent_session_id")
        session_id = session.get("id")
        nesting_level = genie_metadata.get("nesting_level", 0)

        if genie_metadata.get("is_genie_slave") and parent_id:
            # This is a child session
            if parent_id not in slave_sessions_by_parent:
                slave_sessions_by_parent[parent_id] = []
            slave_sessions_by_parent[parent_id].append(session)
            app_logger.debug(f"[Session Hierarchy] Child: {session_id} (L{nesting_level}) -> parent: {parent_id}")
        else:
            # This is a parent/normal session
            parent_sessions.append(session)
            app_logger.debug(f"[Session Hierarchy] Parent/Normal: {session_id}")

    # Sort parent sessions by last_updated (most recent first)
    def sort_key(session):
        last_updated = session.get("last_updated") or session.get("created_at", "")
        if last_updated == "Unknown" or not last_updated:
            return datetime.min.isoformat()
        return last_updated

    parent_sessions.sort(key=sort_key, reverse=True)

    # Sort child sessions by sequence number (if available) or created_at
    for parent_id, slaves in slave_sessions_by_parent.items():
        slaves.sort(key=lambda s: s.get("genie_metadata", {}).get("slave_sequence_number", 0))

        # Mark last child for proper connector styling (└─ vs ├─)
        if slaves:
            slaves[-1]["genie_metadata"]["is_last_child"] = True
            app_logger.debug(f"[Session Hierarchy] Marked last child: {slaves[-1].get('id')} for parent {parent_id}")

    # Build final list with children inserted after their parents (recursively for nested Genies)
    def add_session_with_children(session_id, sessions_dict, added_ids, depth=0):
        """Recursively add a session and all its children (nested hierarchy support)"""
        indent = "  " * depth

        if session_id in added_ids:
            app_logger.debug(f"{indent}[Recursive Build] Skipping {session_id} (already added)")
            return  # Already added (prevent duplicates)

        if session_id not in sessions_dict:
            app_logger.debug(f"{indent}[Recursive Build] Session {session_id} not found in sessions_dict")
            return  # Session not found

        session = sessions_dict[session_id]
        final_sessions.append(session)
        added_ids.add(session_id)
        app_logger.debug(f"{indent}[Recursive Build] Added session {session_id} (depth={depth})")

        # Recursively add children
        if session_id in slave_sessions_by_parent:
            children = slave_sessions_by_parent[session_id]
            app_logger.debug(f"{indent}[Recursive Build] Session {session_id} has {len(children)} children")
            for child in children:
                add_session_with_children(child.get("id"), sessions_dict, added_ids, depth + 1)
        else:
            app_logger.debug(f"{indent}[Recursive Build] Session {session_id} has no children")

    final_sessions = []
    added_ids = set()

    # Add all parent sessions with their nested children
    app_logger.debug(f"[Recursive Build] Starting with {len(parent_sessions)} top-level sessions")
    for parent in parent_sessions:
        add_session_with_children(parent.get("id"), session_by_id, added_ids, depth=0)

    # Add any orphan children (parent not in list) at the end
    for parent_id, slaves in slave_sessions_by_parent.items():
        if parent_id not in session_by_id:
            final_sessions.extend(slaves)

    session_summaries = final_sessions

    # Calculate total count before pagination
    total_count = len(session_summaries)

    # Apply pagination if limit is specified
    if limit is not None:
        paginated_sessions = session_summaries[offset:offset + limit]
        has_more = offset + limit < total_count
    else:
        paginated_sessions = session_summaries
        has_more = False

    app_logger.debug(f"[FINAL RESULT] Returning {len(paginated_sessions)} of {total_count} sessions (offset={offset}, limit={limit}, has_more={has_more})")
    for i, session in enumerate(paginated_sessions[:10], 1):
        session_id = session.get("id", "unknown")[:12]
        is_slave = session.get("genie_metadata", {}).get("is_genie_slave", False)
        nesting_level = session.get("genie_metadata", {}).get("nesting_level", "N/A")
        name = session.get("name", "Unnamed")[:30]
        app_logger.debug(f"[FINAL] {i}. {session_id}... - {name} (slave={is_slave}, level={nesting_level})")

    return {
        "sessions": paginated_sessions,
        "total_count": total_count,
        "has_more": has_more
    }

async def delete_session(user_uuid: str, session_id: str, archived_reason: str = None) -> bool:
    """Archives a session by marking it as archived instead of deleting the file.

    Args:
        user_uuid: The user's UUID
        session_id: The session ID to archive
        archived_reason: Optional reason for archiving (e.g., "User manually deleted session")
    """
    session_path = _find_session_path(user_uuid, session_id)
    if not session_path:
        app_logger.error(f"Cannot archive session '{session_id}' for user '{user_uuid}': Session not found.")
        return False # Indicate failure due to not finding the session

    app_logger.info(f"Attempting to archive session file: {session_path}")
    try:
        if session_path.is_file():
            # Load the session data
            async with aiofiles.open(session_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                session_data = json.loads(content)

            # Mark as archived
            session_data["archived"] = True
            session_data["is_archived"] = True
            session_data["archived_at"] = datetime.now(timezone.utc).isoformat()
            if archived_reason:
                session_data["archived_reason"] = archived_reason

            # Save back to file
            async with aiofiles.open(session_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(session_data, indent=2, ensure_ascii=False))

            app_logger.info(f"Successfully archived session file: {session_path}")

            # Clean up uploads directory for this session
            _cleanup_session_uploads(user_uuid, session_id)

            return True # Indicate success
        else:
            # This case should ideally not be hit if _find_session_path is correct
            app_logger.warning(f"Session file not found for archiving: {session_path}. Treating as success (already gone).")
            return True # Indicate success (idempotent delete)
    except (OSError, json.JSONDecodeError) as e:
        app_logger.error(f"Error archiving session file '{session_path}': {e}", exc_info=True)
        return False # Indicate failure due to error


async def archive_sessions_by_profile(
    profile_id: str,
    user_uuid: str
) -> dict:
    """
    Archive all sessions for a user that reference the given profile_id.

    Uses the unified relationships REST endpoint to detect affected sessions,
    ensuring consistency with frontend warnings. This creates a single
    source of truth for session detection logic.

    Args:
        profile_id: The ID of the profile being deleted
        user_uuid: The user who owns the sessions

    Returns:
        dict: {
            "archived_count": int,
            "session_ids": [list of archived session IDs],
            "genie_children_archived": int
        }
    """
    archived_sessions = []
    genie_children = []

    try:
        # Call relationship analyzer directly (no HTTP call needed)
        from trusted_data_agent.core.relationship_analyzer import RelationshipAnalyzer

        app_logger.info(f"Analyzing relationships for profile {profile_id}")

        analyzer = RelationshipAnalyzer()
        result = await analyzer.analyze_artifact_relationships(
            artifact_type="profile",
            artifact_id=profile_id,
            user_uuid=user_uuid,
            include_archived=False,  # Only get active sessions
            limit=1000,  # High limit to get all sessions
            full=False
        )

        sessions_data = result.get("relationships", {}).get("sessions", {})
        affected_sessions = sessions_data.get("items", [])

        # Filter to only active sessions (not already archived)
        active_sessions = [s for s in affected_sessions if not s.get("archived")]

        app_logger.info(
            f"Unified endpoint found {len(active_sessions)} active sessions for profile {profile_id}"
        )

        # Archive each affected session
        for session_info in active_sessions:
            session_id = session_info.get("session_id")

            # Check if this is a Genie child session
            is_genie_child = session_info.get("is_genie_child", False)
            if is_genie_child:
                genie_children.append(session_id)

            try:
                # Use existing delete_session() archive function with reason
                success = await delete_session(
                    user_uuid,
                    session_id,
                    archived_reason=f"Profile '{profile_id}' was deleted"
                )

                if success:
                    archived_sessions.append(session_id)
                    app_logger.info(
                        f"Archived session {session_id} (profile {profile_id} deleted)"
                    )

            except Exception as e:
                app_logger.error(f"Failed to archive session {session_id}: {e}", exc_info=True)
                continue

        # Update genie_session_links table for archived children
        if genie_children:
            try:
                conn = get_auth_db_connection()
                cursor = conn.cursor()

                # Check if archived column exists (for backward compatibility)
                cursor.execute("PRAGMA table_info(genie_session_links)")
                columns = [row[1] for row in cursor.fetchall()]

                if "archived" in columns:
                    placeholders = ",".join("?" * len(genie_children))
                    cursor.execute(
                        f"UPDATE genie_session_links SET archived = 1 WHERE slave_session_id IN ({placeholders})",
                        genie_children
                    )
                    conn.commit()
                    app_logger.info(f"Updated genie_session_links archived flag for {len(genie_children)} children")

                conn.close()
            except Exception as e:
                app_logger.error(f"Error updating genie_session_links: {e}", exc_info=True)

        app_logger.info(
            f"Archive by profile complete: {len(archived_sessions)} sessions archived "
            f"({len(genie_children)} Genie children)"
        )

        return {
            "archived_count": len(archived_sessions),
            "session_ids": archived_sessions,
            "genie_children_archived": len(genie_children)
        }

    except Exception as e:
        app_logger.error(f"Error in archive_sessions_by_profile: {e}", exc_info=True)
        return {"archived_count": 0, "session_ids": [], "genie_children_archived": 0}


async def archive_sessions_by_collection(
    collection_id: str,
    user_uuid: str
) -> dict:
    """
    Archive all sessions for a user that use the given collection_id.

    Uses the unified relationships REST endpoint to detect affected sessions,
    ensuring consistency with frontend warnings. This creates a single
    source of truth for session detection logic.

    Args:
        collection_id: The ID of the collection being deleted
        user_uuid: The user who owns the sessions

    Returns:
        dict: {
            "archived_count": int,
            "session_ids": [list of archived session IDs]
        }
    """
    archived_sessions = []

    try:
        # Call unified relationships endpoint to get list of affected sessions
        from quart import current_app
        from trusted_data_agent.auth.middleware import create_internal_jwt
        import httpx

        # Create internal JWT for service-to-service call
        internal_token = create_internal_jwt(user_uuid)

        # Call relationship analyzer directly (no HTTP call needed)
        from trusted_data_agent.core.relationship_analyzer import RelationshipAnalyzer

        app_logger.info(f"[ARCHIVE] Analyzing relationships for collection {collection_id}")
        app_logger.info(f"[ARCHIVE] User: {user_uuid}, Collection: {collection_id}")

        analyzer = RelationshipAnalyzer()
        result = await analyzer.analyze_artifact_relationships(
            artifact_type="collection",
            artifact_id=collection_id,
            user_uuid=user_uuid,
            include_archived=False,  # Only get active sessions
            limit=1000,  # High limit to get all sessions
            full=False
        )

        sessions_data = result.get("relationships", {}).get("sessions", {})
        affected_sessions = sessions_data.get("items", [])

        # Filter to only active sessions (not already archived)
        active_sessions = [s for s in affected_sessions if not s.get("archived")]

        app_logger.info(f"[ARCHIVE] Relationship analyzer returned {len(affected_sessions)} total sessions")
        app_logger.info(f"[ARCHIVE] Filtered to {len(active_sessions)} active sessions to archive")
        for session in active_sessions:
            app_logger.info(f"[ARCHIVE]   - Session {session.get('session_id')} ({session.get('session_name', 'Unnamed')})")

        # Archive each affected session
        for session_info in active_sessions:
            session_id = session_info.get("session_id")

            try:
                # Use existing delete_session() archive function with reason
                app_logger.info(f"[ARCHIVE] Archiving session {session_id}...")
                success = await delete_session(
                    user_uuid,
                    session_id,
                    archived_reason=f"Collection '{collection_id}' was deleted"
                )
                app_logger.info(f"[ARCHIVE] delete_session() returned: {success}")
                if not success:
                    app_logger.error(f"[ARCHIVE] FAILED to archive session {session_id}")

                if success:
                    archived_sessions.append(session_id)
                    app_logger.info(
                        f"Archived session {session_id} (collection {collection_id} deleted)"
                    )

            except Exception as e:
                app_logger.error(f"Failed to archive session {session_id}: {e}", exc_info=True)
                continue

        app_logger.info(
            f"Archive by collection complete: {len(archived_sessions)} sessions archived"
        )

        return {
            "archived_count": len(archived_sessions),
            "session_ids": archived_sessions
        }

    except Exception as e:
        app_logger.error(f"Error in archive_sessions_by_collection: {e}", exc_info=True)
        return {"archived_count": 0, "session_ids": []}


async def archive_sessions_by_mcp_server(
    mcp_server_id: str,
    user_uuid: str
) -> dict:
    """
    Archive all sessions for a user that use the given MCP server.

    Uses the unified relationships REST endpoint to detect affected sessions,
    ensuring consistency with frontend warnings. This creates a single
    source of truth for session detection logic.

    Args:
        mcp_server_id: The ID of the MCP server being deleted
        user_uuid: The user who owns the sessions

    Returns:
        dict: {
            "archived_count": int,
            "session_ids": [list of archived session IDs]
        }
    """
    archived_sessions = []

    try:
        # Call relationship analyzer directly (no HTTP call needed)
        from trusted_data_agent.core.relationship_analyzer import RelationshipAnalyzer

        app_logger.info(f"Analyzing relationships for MCP server {mcp_server_id}")

        analyzer = RelationshipAnalyzer()
        result = await analyzer.analyze_artifact_relationships(
            artifact_type="mcp-server",
            artifact_id=mcp_server_id,
            user_uuid=user_uuid,
            include_archived=False,  # Only get active sessions
            limit=1000,  # High limit to get all sessions
            full=False
        )

        sessions_data = result.get("relationships", {}).get("sessions", {})
        affected_sessions = sessions_data.get("items", [])

        # Filter to only active sessions (not already archived)
        active_sessions = [s for s in affected_sessions if not s.get("archived")]

        app_logger.info(
            f"Unified endpoint found {len(active_sessions)} active sessions for MCP server {mcp_server_id}"
        )

        # Archive each affected session
        for session_info in active_sessions:
            session_id = session_info.get("session_id")

            try:
                # Use existing delete_session() archive function with reason
                success = await delete_session(
                    user_uuid,
                    session_id,
                    archived_reason=f"MCP server '{mcp_server_id}' was deleted"
                )

                if success:
                    archived_sessions.append(session_id)
                    app_logger.info(
                        f"Archived session {session_id} (MCP server {mcp_server_id} deleted)"
                    )

            except Exception as e:
                app_logger.error(f"Failed to archive session {session_id}: {e}", exc_info=True)
                continue

        app_logger.info(
            f"Archive by MCP server complete: {len(archived_sessions)} sessions archived"
        )

        return {
            "archived_count": len(archived_sessions),
            "session_ids": archived_sessions
        }

    except Exception as e:
        app_logger.error(f"Error in archive_sessions_by_mcp_server: {e}", exc_info=True)
        return {"archived_count": 0, "session_ids": []}


async def archive_sessions_by_llm_config(
    llm_config_id: str,
    user_uuid: str
) -> dict:
    """
    Archive all sessions for a user that use the given LLM configuration.

    Uses the unified relationships REST endpoint to detect affected sessions,
    ensuring consistency with frontend warnings. This creates a single
    source of truth for session detection logic.

    Args:
        llm_config_id: The ID of the LLM config being deleted
        user_uuid: The user who owns the sessions

    Returns:
        dict: {
            "archived_count": int,
            "session_ids": [list of archived session IDs]
        }
    """
    archived_sessions = []

    try:
        # Call relationship analyzer directly (no HTTP call needed)
        from trusted_data_agent.core.relationship_analyzer import RelationshipAnalyzer

        app_logger.info(f"Analyzing relationships for LLM config {llm_config_id}")

        analyzer = RelationshipAnalyzer()
        result = await analyzer.analyze_artifact_relationships(
            artifact_type="llm-config",
            artifact_id=llm_config_id,
            user_uuid=user_uuid,
            include_archived=False,  # Only get active sessions
            limit=1000,  # High limit to get all sessions
            full=False
        )

        sessions_data = result.get("relationships", {}).get("sessions", {})
        affected_sessions = sessions_data.get("items", [])

        # Filter to only active sessions (not already archived)
        active_sessions = [s for s in affected_sessions if not s.get("archived")]

        app_logger.info(
            f"Unified endpoint found {len(active_sessions)} active sessions for LLM config {llm_config_id}"
        )

        # Archive each affected session
        for session_info in active_sessions:
            session_id = session_info.get("session_id")

            try:
                # Use existing delete_session() archive function with reason
                success = await delete_session(
                    user_uuid,
                    session_id,
                    archived_reason=f"LLM config '{llm_config_id}' was deleted"
                )

                if success:
                    archived_sessions.append(session_id)
                    app_logger.info(
                        f"Archived session {session_id} (LLM config {llm_config_id} deleted)"
                    )

            except Exception as e:
                app_logger.error(f"Failed to archive session {session_id}: {e}", exc_info=True)
                continue

        app_logger.info(
            f"Archive by LLM config complete: {len(archived_sessions)} sessions archived"
        )

        return {
            "archived_count": len(archived_sessions),
            "session_ids": archived_sessions
        }

    except Exception as e:
        app_logger.error(f"Error in archive_sessions_by_llm_config: {e}", exc_info=True)
        return {"archived_count": 0, "session_ids": []}


def _cleanup_session_uploads(user_uuid: str, session_id: str):
    """Remove the uploads directory for a session when it is deleted/archived."""
    import shutil
    safe_user_uuid = "".join(c for c in user_uuid if c.isalnum() or c in ['-', '_'])
    safe_session_id = "".join(c for c in session_id if c.isalnum() or c in ['-', '_'])
    upload_dir = SESSIONS_DIR / safe_user_uuid / "uploads" / safe_session_id
    if upload_dir.is_dir():
        try:
            shutil.rmtree(upload_dir)
            app_logger.info(f"Cleaned up uploads directory for session {session_id}")
        except OSError as e:
            app_logger.warning(f"Failed to clean up uploads directory for session {session_id}: {e}")

# --- MODIFICATION START: Rename and refactor add_to_history ---
async def add_message_to_histories(user_uuid: str, session_id: str, role: str, content: str, html_content: str | None = None, source: str | None = None, profile_tag: str | None = None, is_session_primer: bool = False, attachments: list | None = None, extension_specs: list | None = None, skill_specs: list | None = None):
    """
    Adds a message to the appropriate histories, decoupling UI from LLM context.
    - `content` (plain text) is *always* added to the LLM's chat_object.
    - `html_content` (if provided) is added to the UI's session_history.
    - If `html_content` is not provided, `content` is used for the UI.
    - `profile_tag` (if provided) stores which profile was used for this message.
    - `is_session_primer` (if True) marks this message as part of session initialization.
    """
    async with _session_transaction(user_uuid, session_id) as session_data:
        if not session_data:
            app_logger.warning(f"Could not add history: Session {session_id} not found for user {user_uuid}.")
            return

        # --- 1. Add to UI History (session_history) ---
        ui_content = html_content if html_content is not None else content

        session_history = session_data.setdefault('session_history', [])

        # Determine the next turn number
        next_turn_number = 1
        if session_history:
            last_message = session_history[-1]
            last_turn_number = last_message.get('turn_number', 0)
            if role == 'user':
                next_turn_number = last_turn_number + 1
            else:
                next_turn_number = last_turn_number

        message_to_append = {
            'role': role,
            'content': ui_content,
            'isValid': True,
            'turn_number': next_turn_number,
        }

        if source:
            message_to_append['source'] = source
        if profile_tag:
            message_to_append['profile_tag'] = profile_tag
        if is_session_primer:
            message_to_append['is_session_primer'] = True
        if attachments and role == 'user':
            message_to_append['attachments'] = [
                {k: v for k, v in att.items() if k != 'extracted_text'}
                for att in attachments
            ]
        if extension_specs and role == 'user':
            message_to_append['extension_specs'] = extension_specs
        if skill_specs and role == 'user':
            message_to_append['skill_specs'] = skill_specs

        session_history.append(message_to_append)

        # --- 2. Add to LLM History (chat_object) ---
        provider_in_session = session_data.get("license_info", {}).get("provider")
        current_provider = APP_CONFIG.CURRENT_PROVIDER
        provider = provider_in_session or current_provider
        if not provider:
            app_logger.warning(f"Could not determine LLM provider for role conversion in session {session_id}. Defaulting role.")
            provider = "Unknown"

        llm_role = 'model' if role == 'assistant' and provider == 'Google' else role

        chat_object_history = session_data.setdefault('chat_object', [])

        llm_turn_number = 1
        if chat_object_history:
            last_llm_message = chat_object_history[-1]
            last_llm_turn = last_llm_message.get('turn_number', 0)
            if llm_role == 'user':
                llm_turn_number = last_llm_turn + 1
            else:
                llm_turn_number = last_llm_turn

        llm_message = {
            'role': llm_role,
            'content': content,
            'isValid': True,
            'turn_number': llm_turn_number
        }
        if attachments and role == 'user':
            llm_message['has_attachments'] = True
        chat_object_history.append(llm_message)

async def update_session_name(user_uuid: str, session_id: str, new_name: str):
    async with _session_transaction(user_uuid, session_id) as session_data:
        if not session_data:
            app_logger.warning(f"Could not update name: Session {session_id} not found for user {user_uuid}.")
            return
        session_data['name'] = new_name

    # Post-save operations (outside lock)
    try:
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.consumption_manager import ConsumptionManager

        with get_db_session() as db_session:
            manager = ConsumptionManager(db_session)
            manager.update_session_name(user_uuid, session_id, new_name)
    except Exception as e:
        app_logger.warning(f"Failed to update session name in consumption database: {e}")

    notification_queues = APP_STATE.get("notification_queues", {}).get(user_uuid, set())
    if notification_queues:
        notification = {
            "type": "session_name_update",
            "payload": {"session_id": session_id, "newName": new_name}
        }
        for queue in notification_queues:
            asyncio.create_task(queue.put(notification))


async def set_session_context_limit(user_uuid: str, session_id: str, context_limit: int | None):
    """Set or clear a session-level context limit override."""
    async with _session_transaction(user_uuid, session_id) as session_data:
        if not session_data:
            return
        if context_limit is None:
            session_data.pop('session_context_limit_override', None)
        else:
            session_data['session_context_limit_override'] = int(context_limit)


async def update_token_count(user_uuid: str, session_id: str, input_tokens: int, output_tokens: int):
    """Updates the token counts for a given session."""
    async with _session_transaction(user_uuid, session_id) as session_data:
        if not session_data:
            app_logger.warning(f"Could not update tokens: Session {session_id} not found for user {user_uuid}.")
            return
        session_data['input_tokens'] = session_data.get('input_tokens', 0) + input_tokens
        session_data['output_tokens'] = session_data.get('output_tokens', 0) + output_tokens

    # Post-save operations (outside lock for minimal lock hold time)
    try:
        from trusted_data_agent.auth.token_quota import record_token_usage
        record_token_usage(user_uuid, input_tokens, output_tokens)
        app_logger.debug(f"Recorded token usage for user {user_uuid}: input={input_tokens}, output={output_tokens}")
    except Exception as e:
        app_logger.error(f"Failed to record token usage for user {user_uuid}: {e}")

    # --- CONSUMPTION TRACKING ---
    try:
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.consumption_manager import ConsumptionManager

        with get_db_session() as db_session:
            manager = ConsumptionManager(db_session)
            manager.increment_request_counter(user_uuid)
            app_logger.debug(f"Incremented request counter for user {user_uuid}")
    except Exception as e:
        app_logger.warning(f"Failed to update consumption tracking for user {user_uuid}: {e}")


async def update_models_used(user_uuid: str, session_id: str, provider: str, model: str, profile_tag: str | None = None, planning_phase: str | None = None):
    """
    Adds the current model/profile to the list used in the session.

    Args:
        planning_phase: Optional planning phase indicator ("strategic" | "tactical" | "conversation")
                       for dual-model tracking
    """
    app_logger.debug(f"update_models_used called for session {session_id} with provider={provider}, model={model}, profile_tag={profile_tag}, planning_phase={planning_phase}")
    async with _session_transaction(user_uuid, session_id) as session_data:
        if not session_data:
            app_logger.warning(f"Could not update models used: Session {session_id} not found for user {user_uuid}.")
            return
        # Keep models_used for backwards compatibility
        models_used = session_data.get('models_used', [])
        model_string = f"{provider}/{model}"
        if model_string not in models_used:
            models_used.append(model_string)
            session_data['models_used'] = models_used

        # Track strategic vs tactical usage (NEW: Dual-model traceability)
        if planning_phase and planning_phase in ["strategic", "tactical", "tactical_fastpath", "conversation"]:
            if "dual_model_usage" not in session_data:
                session_data["dual_model_usage"] = {
                    "strategic": [],
                    "tactical": [],
                    "tactical_fastpath": [],
                    "conversation": []
                }

            phase_models = session_data["dual_model_usage"][planning_phase]
            if model_string not in phase_models:
                phase_models.append(model_string)
                app_logger.debug(f"[Dual-Model] Tracked {model_string} as {planning_phase} model")

        # Add profile tag to profile_tags_used
        if profile_tag:
            profile_tags_used = session_data.get('profile_tags_used', [])
            if profile_tag not in profile_tags_used:
                profile_tags_used.append(profile_tag)
                session_data['profile_tags_used'] = profile_tags_used

        session_data['provider'] = provider
        session_data['model'] = model
        session_data['profile_tag'] = profile_tag


async def update_last_turn_data(user_uuid: str, session_id: str, turn_data: dict):
    """Saves the most recent turn's action history and plans to the session file."""
    # Capture values needed for post-save consumption tracking
    _session_name = None
    _consumption_data = None

    async with _session_transaction(user_uuid, session_id) as session_data:
        if not session_data:
            app_logger.warning(f"Could not update last turn data: Session {session_id} not found for user {user_uuid}.")
            return
        # Ensure the structure exists
        if "last_turn_data" not in session_data:
            session_data["last_turn_data"] = {}
        if "workflow_history" not in session_data["last_turn_data"] or not isinstance(session_data["last_turn_data"]["workflow_history"], list):
            session_data["last_turn_data"]["workflow_history"] = []

        if isinstance(turn_data, dict):
            turn_data["isValid"] = True

        # --- EFFICIENCY TRACKING ---
        workflow_history = session_data["last_turn_data"]["workflow_history"]
        if len(workflow_history) > 0 and isinstance(turn_data, dict):
            previous_turn = workflow_history[-1]
            previous_output = previous_turn.get('turn_output_tokens', 0)
            current_output = turn_data.get('turn_output_tokens', 0)
            previous_had_rag = previous_turn.get('rag_source_collection_id') is not None

            provider = turn_data.get('provider', 'Unknown')
            model = turn_data.get('model', 'unknown')
            output_tokens = turn_data.get('turn_output_tokens', 0)

            cost_per_token = 0.0
            if output_tokens > 0:
                from trusted_data_agent.core.cost_manager import get_cost_manager
                cost_manager = get_cost_manager()
                turn_cost = cost_manager.calculate_cost(provider, model, 0, output_tokens)
                cost_per_token = turn_cost / output_tokens if output_tokens > 0 else 0.0

            if previous_output > 0:
                from trusted_data_agent.core.efficiency_tracker import get_efficiency_tracker
                tracker = get_efficiency_tracker()
                tracker.record_improvement(
                    session_id=session_id,
                    turn_index=len(workflow_history),
                    previous_output_tokens=previous_output,
                    current_output_tokens=current_output,
                    had_rag=previous_had_rag,
                    cost_per_output_token=cost_per_token,
                    user_uuid=user_uuid
                )

                current_turn_has_rag = turn_data.get('rag_source_collection_id') is not None
                if current_turn_has_rag and current_output < previous_output:
                    tokens_saved = previous_output - current_output
                    turn_data['rag_efficiency_gain'] = tokens_saved
                    app_logger.debug(f"RAG efficiency gain for current turn: {tokens_saved} tokens saved")

        # Append the new turn data
        session_data["last_turn_data"]["workflow_history"].append(turn_data)

        # Capture data for post-save consumption tracking (avoid secondary load)
        _session_name = session_data.get('name') or 'Untitled Session'
        turn_number = len(session_data["last_turn_data"]["workflow_history"])
        _consumption_data = {
            "turn_number": turn_number,
            "input_tokens": turn_data.get('turn_input_tokens', 0),
            "output_tokens": turn_data.get('turn_output_tokens', 0),
            "provider": turn_data.get('provider', 'Unknown'),
            "model": turn_data.get('model', 'unknown'),
            "status": turn_data.get('status', 'success'),
            "rag_used": turn_data.get('rag_source_collection_id') is not None,
            "rag_tokens_saved": turn_data.get('rag_efficiency_gain', 0) if turn_data.get('rag_source_collection_id') is not None else 0,
            "user_query": turn_data.get('user_query', ''),
        }

    # --- CONSUMPTION TRACKING (outside lock for minimal lock hold time) ---
    if _consumption_data:
        try:
            from trusted_data_agent.auth.database import get_db_session
            from trusted_data_agent.auth.consumption_manager import ConsumptionManager
            from trusted_data_agent.core.cost_manager import get_cost_manager

            with get_db_session() as db_session:
                manager = ConsumptionManager(db_session)

                cost_manager = get_cost_manager()
                cost_usd = cost_manager.calculate_cost(
                    _consumption_data["provider"], _consumption_data["model"],
                    _consumption_data["input_tokens"], _consumption_data["output_tokens"]
                )
                cost_usd_cents = int(cost_usd * 1000000)
                app_logger.info(f"[Cost Tracking] {_consumption_data['provider']}/{_consumption_data['model']}: {_consumption_data['input_tokens']}in + {_consumption_data['output_tokens']}out = ${cost_usd:.6f} ({cost_usd_cents} micro-dollars)")

                manager.record_turn(
                    user_id=user_uuid,
                    session_id=session_id,
                    turn_number=_consumption_data["turn_number"],
                    input_tokens=_consumption_data["input_tokens"],
                    output_tokens=_consumption_data["output_tokens"],
                    provider=_consumption_data["provider"],
                    model=_consumption_data["model"],
                    status=_consumption_data["status"],
                    rag_used=_consumption_data["rag_used"],
                    rag_tokens_saved=_consumption_data["rag_tokens_saved"],
                    cost_usd_cents=cost_usd_cents,
                    user_query=_consumption_data["user_query"],
                    session_name=_session_name
                )
                app_logger.debug(f"Recorded turn metrics for user {user_uuid}, session {session_id}, turn {_consumption_data['turn_number']}")
        except Exception as e:
            app_logger.warning(f"Failed to record turn metrics for user {user_uuid}: {e}")


async def append_extension_results_to_turn(
    user_uuid: str,
    session_id: str,
    extension_results: dict,
    extension_events: list = None,
    extension_input_tokens: int = 0,
    extension_output_tokens: int = 0,
):
    """
    Append extension results and lifecycle events to the most recent turn
    in workflow_history. Called after extensions complete in execution_service.py,
    since extensions run AFTER the turn is already saved by update_last_turn_data().

    Args:
        user_uuid: User UUID for session lookup
        session_id: Session ID
        extension_results: Serialized extension results dict
        extension_events: List of extension lifecycle events [{type, payload}, ...]
        extension_input_tokens: Total input tokens consumed by extensions (for LLM-calling extensions)
        extension_output_tokens: Total output tokens consumed by extensions
    """
    async with _session_transaction(user_uuid, session_id) as session_data:
        if not session_data:
            app_logger.warning(f"Cannot append extension results: session {session_id} not found")
            return

        workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])
        if not workflow_history:
            app_logger.warning(f"Cannot append extension results: no turns in session {session_id}")
            return  # No modifications — _session_transaction save is a harmless no-op

        # Patch the last turn entry
        last_turn = workflow_history[-1]
        last_turn["extension_results"] = extension_results
        if extension_events:
            last_turn["extension_events"] = extension_events

        # Update turn-level token totals if extensions consumed tokens
        if extension_input_tokens > 0 or extension_output_tokens > 0:
            last_turn["turn_input_tokens"] = last_turn.get("turn_input_tokens", 0) + extension_input_tokens
            last_turn["turn_output_tokens"] = last_turn.get("turn_output_tokens", 0) + extension_output_tokens
            try:
                from trusted_data_agent.core.cost_manager import get_cost_manager
                cost_manager = get_cost_manager()
                provider = last_turn.get("provider", "")
                model = last_turn.get("model", "")
                last_turn["turn_cost"] = cost_manager.calculate_cost(
                    provider, model,
                    last_turn["turn_input_tokens"],
                    last_turn["turn_output_tokens"]
                )
            except Exception:
                pass

        app_logger.debug(f"Appended extension results to last turn in session {session_id}")


# --- MODIFICATION START: Add function to purge only the agent's memory ---
async def purge_session_memory(user_uuid: str, session_id: str) -> bool:
    """
    Resets the agent's LLM context memory (`chat_object`) for a session,
    but leaves the UI history (`session_history`) and plan/trace history
    (`last_turn_data`) intact.
    """
    app_logger.info(f"Attempting to purge agent memory (chat_object) for session '{session_id}', user '{user_uuid}'.")
    try:
        async with _session_transaction(user_uuid, session_id) as session_data:
            if not session_data:
                app_logger.warning(f"Could not purge memory: Session {session_id} not found for user {user_uuid}.")
                return False

            # Mark all existing history as invalid
            session_history = session_data.get('session_history', [])
            history_count = 0
            if isinstance(session_history, list):
                for msg in session_history:
                    if isinstance(msg, dict):
                        msg["isValid"] = False
                        history_count += 1

            workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])
            turn_count = 0
            if isinstance(workflow_history, list):
                for turn in workflow_history:
                    if isinstance(turn, dict):
                        turn["isValid"] = False
                        turn_count += 1

            app_logger.info(f"Marked {history_count} UI messages and {turn_count} turns as invalid for session '{session_id}'.")

            chat_history_for_file = []
            provider_in_session = session_data.get("license_info", {}).get("provider")
            current_provider = APP_CONFIG.CURRENT_PROVIDER
            provider = provider_in_session or current_provider or "Google"

            if provider == "Google":
                initial_history_google = [
                    {"role": "user", "parts": [{"text": "You are a helpful assistant."}]},
                    {"role": "model", "parts": [{"text": "Understood."}]}
                ]
                chat_history_for_file = [{'role': m['role'], 'content': m['parts'][0]['text']} for m in initial_history_google]

            session_data['chat_object'] = chat_history_for_file
            session_data['full_context_sent'] = False

        app_logger.info(f"Successfully reset chat_object for session '{session_id}'. Invalidated existing history.")
        return True

    except Exception as e:
        app_logger.error(f"An unexpected error occurred during memory purge for session '{session_id}': {e}", exc_info=True)
        return False

# --- MODIFICATION START: Add function to toggle turn validity ---
async def toggle_turn_validity(user_uuid: str, session_id: str, turn_id: int) -> bool:
    """
    Toggles the 'isValid' status of a specific turn and its corresponding
    UI messages in the session history and LLM chat_object.
    """
    app_logger.info(f"Toggling validity for turn {turn_id} in session '{session_id}' for user '{user_uuid}'.")
    try:
        async with _session_transaction(user_uuid, session_id) as session_data:
            if not session_data:
                app_logger.warning(f"Could not toggle validity: Session {session_id} not found.")
                return False

            # 1. Toggle validity in workflow_history
            workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])
            turn_found = False
            new_status = None
            if isinstance(workflow_history, list):
                for turn in workflow_history:
                    if isinstance(turn, dict) and turn.get("turn") == turn_id:
                        current_status = turn.get("isValid", True)
                        new_status = not current_status
                        turn["isValid"] = new_status
                        turn_found = True
                        break

            if not turn_found:
                app_logger.warning(f"Turn {turn_id} not found in workflow_history for session {session_id}.")
                return False

            # 2. Toggle validity in session_history (for the UI)
            session_history = session_data.get('session_history', [])
            if isinstance(session_history, list):
                assistant_message_count = 0
                for i, msg in enumerate(session_history):
                    if isinstance(msg, dict) and msg.get('role') == 'assistant':
                        assistant_message_count += 1
                        if assistant_message_count == turn_id:
                            msg['isValid'] = new_status
                            if i > 0 and session_history[i-1].get('role') == 'user':
                                session_history[i-1]['isValid'] = new_status
                            break

            # 3. Toggle validity in chat_object
            chat_object = session_data.get('chat_object', [])
            if isinstance(chat_object, list):
                for msg in chat_object:
                    if isinstance(msg, dict) and msg.get('turn_number') == turn_id:
                        msg['isValid'] = new_status

        return True

    except Exception as e:
        app_logger.error(f"An unexpected error occurred during validity toggle for turn {turn_id}: {e}", exc_info=True)
        return False

# --- MODIFICATION START: Add function to update turn system_events ---
async def update_turn_system_events(user_uuid: str, session_id: str, turn_number: int, system_events: list) -> bool:
    """
    Updates the system_events for a specific turn in the workflow_history.
    This is used when session name generation events need to be added after
    the turn has already been saved.

    Args:
        user_uuid: The user's UUID
        session_id: The session ID
        turn_number: The turn number to update
        system_events: The list of system events to store

    Returns:
        True if successful, False otherwise
    """
    try:
        async with _session_transaction(user_uuid, session_id) as session_data:
            if not session_data:
                app_logger.warning(f"Could not update system_events: Session {session_id} not found for user {user_uuid}.")
                return False

            workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

            turn_found = False
            for turn in workflow_history:
                if turn.get("turn") == turn_number:
                    turn["system_events"] = system_events
                    turn_found = True
                    break

            if not turn_found:
                app_logger.warning(f"Could not update system_events: Turn {turn_number} not found in session {session_id}.")
                return False

        app_logger.debug(f"Updated system_events for turn {turn_number} in session {session_id}")
        return True

    except Exception as e:
        app_logger.error(f"Failed to update system_events for turn {turn_number}: {e}", exc_info=True)
        return False

# --- MODIFICATION START: Add function to update turn token counts ---
async def update_turn_token_counts(user_uuid: str, session_id: str, turn_number: int, input_tokens: int, output_tokens: int) -> bool:
    """
    Updates the token counts for a specific turn in the workflow_history.
    This is used when session name generation tokens need to be added after
    the turn has already been saved.

    Args:
        user_uuid: The user's UUID
        session_id: The session ID
        turn_number: The turn number to update
        input_tokens: The total input tokens for the turn (including session name)
        output_tokens: The total output tokens for the turn (including session name)

    Returns:
        True if successful, False otherwise
    """
    try:
        async with _session_transaction(user_uuid, session_id) as session_data:
            if not session_data:
                app_logger.warning(f"Could not update token counts: Session {session_id} not found for user {user_uuid}.")
                return False

            workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

            turn_found = False
            for turn in workflow_history:
                if turn.get("turn") == turn_number:
                    turn["input_tokens"] = input_tokens
                    turn["output_tokens"] = output_tokens
                    turn["turn_input_tokens"] = input_tokens
                    turn["turn_output_tokens"] = output_tokens
                    if "session_input_tokens" in turn:
                        turn["session_input_tokens"] = session_data.get("input_tokens", input_tokens)
                    if "session_output_tokens" in turn:
                        turn["session_output_tokens"] = session_data.get("output_tokens", output_tokens)

                    try:
                        from trusted_data_agent.core.cost_manager import CostManager
                        cost_manager = CostManager()
                        provider = session_data.get("provider", "")
                        model = session_data.get("model", "")
                        turn_cost = cost_manager.calculate_cost(provider, model, input_tokens, output_tokens)
                        turn["turn_cost"] = turn_cost
                    except Exception as e:
                        app_logger.warning(f"Failed to calculate turn cost: {e}")

                    try:
                        session_cost = 0.0
                        for i, t in enumerate(workflow_history):
                            if i + 1 <= turn_number:
                                if "turn_cost" in t:
                                    session_cost += float(t["turn_cost"])
                        turn["session_cost_usd"] = session_cost
                    except Exception as e:
                        app_logger.warning(f"Failed to recalculate session_cost_usd: {e}")

                    turn_found = True
                    app_logger.debug(f"Updated turn {turn_number} token counts: {input_tokens} in / {output_tokens} out")
                    break

            if not turn_found:
                app_logger.warning(f"Could not update token counts: Turn {turn_number} not found in session {session_id}.")
                return False

        return True

    except Exception as e:
        app_logger.error(f"Failed to update token counts for turn {turn_number}: {e}", exc_info=True)
        return False
# --- MODIFICATION END ---

# --- MODIFICATION START: Add function to update turn feedback ---
async def update_turn_feedback(user_uuid: str, session_id: str, turn_id: int, vote: str | None) -> bool:
    """
    Updates the feedback (upvote/downvote) for a specific turn in the workflow_history
    and propagates the feedback to the corresponding RAG case.

    Args:
        user_uuid: The user's UUID
        session_id: The session ID
        turn_id: The turn number to update
        vote: 'up', 'down', or None to clear the vote

    Returns:
        True if successful, False otherwise
    """
    import asyncio
    from trusted_data_agent.core.config import APP_STATE, APP_CONFIG

    case_id = None
    try:
        async with _session_transaction(user_uuid, session_id) as session_data:
            if not session_data:
                app_logger.warning(f"Could not update feedback: Session {session_id} not found for user {user_uuid}.")
                return False

            workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

            turn_found = False
            for turn in workflow_history:
                if turn.get("turn") == turn_id:
                    if vote is None:
                        turn.pop("feedback", None)
                    else:
                        turn["feedback"] = vote
                    turn_found = True
                    case_id = turn.get("case_id")
                    app_logger.info(f"Updated feedback for turn {turn_id} in session {session_id}: {vote}")
                    break

            if not turn_found:
                app_logger.warning(f"Turn {turn_id} not found in workflow_history for session {session_id}")
                return False

        # Post-save: Update RAG case (outside lock)
        if APP_CONFIG.RAG_ENABLED and case_id:
            retriever = APP_STATE.get('rag_retriever_instance')
            if retriever:
                feedback_score = 1 if vote == 'up' else -1 if vote == 'down' else 0
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(retriever.update_case_feedback(case_id, feedback_score))
                    app_logger.info(f"Queued RAG case {case_id} feedback update: {feedback_score}")
                except Exception as e:
                    app_logger.error(f"Failed to update RAG case {case_id}: {e}", exc_info=True)

        return True

    except Exception as e:
        app_logger.error(f"Error updating feedback for turn {turn_id}: {e}", exc_info=True)
        return False

async def add_case_id_to_turn(user_uuid: str, session_id: str, turn_id: int, case_id: str) -> bool:
    """
    Adds a RAG case_id to a specific turn in the workflow_history.

    Args:
        user_uuid: The user's UUID
        session_id: The session ID
        turn_id: The turn number to update
        case_id: The RAG case ID to associate with this turn

    Returns:
        True if successful, False otherwise
    """
    try:
        async with _session_transaction(user_uuid, session_id) as session_data:
            if not session_data:
                app_logger.warning(f"Could not add case_id: Session {session_id} not found for user {user_uuid}.")
                return False

            workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

            turn_found = False
            for turn in workflow_history:
                if turn.get("turn") == turn_id:
                    turn["case_id"] = case_id
                    turn_found = True
                    app_logger.debug(f"Added case_id {case_id} to turn {turn_id} in session {session_id}")
                    break

            if not turn_found:
                app_logger.warning(f"Turn {turn_id} not found in workflow_history for session {session_id}")
                return False

        return True

    except Exception as e:
        app_logger.error(f"Error adding case_id to turn {turn_id}: {e}", exc_info=True)
        return False


# --- GENIE SESSION MANAGEMENT FUNCTIONS ---

async def record_genie_session_link(parent_session_id: str, slave_session_id: str, slave_profile_id: str, slave_profile_tag: str, user_uuid: str, execution_order: int = 0, nesting_level: int = 0) -> bool:
    """
    Record a link between a Genie parent session and a slave session.

    Args:
        parent_session_id: The Genie coordinator session ID
        slave_session_id: The spawned slave session ID
        slave_profile_id: The profile ID used for the slave session
        slave_profile_tag: The profile tag (e.g., @CHAT, @RAG)
        user_uuid: The user who owns both sessions
        execution_order: The order in which the slave was invoked
        nesting_level: Depth in nested Genie hierarchy (0 = direct slave, 1 = slave of slave, etc.)

    Returns:
        True if successful, False otherwise
    """
    try:
        from trusted_data_agent.auth.database import get_db_session
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root

        db_path = str(get_project_root() / "tda_auth.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO genie_session_links
            (parent_session_id, slave_session_id, slave_profile_id, slave_profile_tag, user_uuid, execution_order, nesting_level)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (parent_session_id, slave_session_id, slave_profile_id, slave_profile_tag, user_uuid, execution_order, nesting_level))

        conn.commit()
        conn.close()

        app_logger.info(f"Recorded genie session link: {parent_session_id} -> child {slave_session_id} (@{slave_profile_tag})")
        return True

    except Exception as e:
        app_logger.error(f"Failed to record genie session link: {e}", exc_info=True)
        return False


async def get_genie_slave_sessions(parent_session_id: str, user_uuid: str) -> list:
    """
    Get all child sessions for a Genie parent session.

    Note: Function name preserved for API compatibility.

    Args:
        parent_session_id: The Genie coordinator session ID
        user_uuid: The user who owns the sessions

    Returns:
        List of child session info dicts
    """
    try:
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root

        db_path = str(get_project_root() / "tda_auth.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT slave_session_id, slave_profile_id, slave_profile_tag, created_at, status, execution_order
            FROM genie_session_links
            WHERE parent_session_id = ? AND user_uuid = ?
            ORDER BY execution_order
        """, (parent_session_id, user_uuid))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    except Exception as e:
        app_logger.error(f"Failed to get genie child sessions: {e}", exc_info=True)
        return []


async def get_genie_parent_session(slave_session_id: str, user_uuid: str) -> dict | None:
    """
    Get the parent Genie session for a child session.

    Note: Function name preserved for API compatibility.

    Args:
        slave_session_id: The child session ID (parameter name preserved for API compatibility)
        user_uuid: The user who owns the sessions

    Returns:
        Parent session link info or None if not a child session
    """
    try:
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root

        db_path = str(get_project_root() / "tda_auth.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT parent_session_id, slave_profile_id, slave_profile_tag, created_at, status, execution_order, nesting_level
            FROM genie_session_links
            WHERE slave_session_id = ? AND user_uuid = ?
        """, (slave_session_id, user_uuid))

        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    except Exception as e:
        app_logger.error(f"Failed to get genie parent session: {e}", exc_info=True)
        return None


async def cleanup_genie_slave_sessions(
    parent_session_id: str,
    user_uuid: str,
    _depth: int = 0,
    archived_reason: str = None
) -> list:
    """
    Clean up (archive) all child sessions when a Genie parent session is deleted.
    Recursively handles nested Genie sessions (children that are themselves parents).

    Args:
        parent_session_id: The Genie coordinator session ID
        user_uuid: The user who owns the sessions
        _depth: Internal recursion depth guard (max 5)
        archived_reason: Optional reason for archiving (passed to delete_session)

    Returns:
        List of all deleted (archived) child session IDs, including nested descendants
    """
    all_deleted = []

    if _depth > 5:
        app_logger.warning(f"Max nesting depth reached for cleanup of parent {parent_session_id}")
        return all_deleted

    try:
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root

        # Get all direct child sessions
        slaves = await get_genie_slave_sessions(parent_session_id, user_uuid)

        # Delete each child session, recursing into nested Genie children first
        for slave in slaves:
            slave_session_id = slave.get('slave_session_id')
            if slave_session_id:
                # Recurse: if this child is also a Genie parent, clean up its children first
                nested_deleted = await cleanup_genie_slave_sessions(
                    slave_session_id, user_uuid, _depth=_depth + 1, archived_reason=archived_reason
                )
                all_deleted.extend(nested_deleted)

                await delete_session(user_uuid, slave_session_id, archived_reason=archived_reason)
                all_deleted.append(slave_session_id)
                app_logger.info(f"Deleted genie child session: {slave_session_id}")

        # Remove links from database
        db_path = str(get_project_root() / "tda_auth.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM genie_session_links
            WHERE parent_session_id = ? AND user_uuid = ?
        """, (parent_session_id, user_uuid))

        conn.commit()
        conn.close()

        # Also clear the in-memory cache in GenieCoordinator
        try:
            from trusted_data_agent.agent.genie_coordinator import SlaveSessionTool
            # Remove all cache entries for this parent session
            keys_to_remove = [
                key for key in SlaveSessionTool._session_cache.keys()
                if key.startswith(f"{parent_session_id}:")
            ]
            for key in keys_to_remove:
                del SlaveSessionTool._session_cache[key]
            if keys_to_remove:
                app_logger.debug(f"Cleared {len(keys_to_remove)} in-memory cache entries for parent {parent_session_id}")
        except ImportError:
            pass  # GenieCoordinator not available, skip cache cleanup
        except Exception as cache_err:
            app_logger.warning(f"Failed to clear genie session cache: {cache_err}")

        app_logger.info(f"Cleaned up {len(slaves)} genie child sessions for parent {parent_session_id}")
        return all_deleted

    except Exception as e:
        app_logger.error(f"Failed to cleanup genie child sessions: {e}", exc_info=True)
        return all_deleted


async def update_genie_slave_status(slave_session_id: str, user_uuid: str, status: str) -> bool:
    """
    Update the status of a genie child session link.

    Args:
        slave_session_id: The child session ID (parameter name preserved for API compatibility)
        user_uuid: The user who owns the sessions
        status: New status ('active', 'completed', 'failed')

    Returns:
        True if successful, False otherwise
    """
    try:
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root

        db_path = str(get_project_root() / "tda_auth.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE genie_session_links
            SET status = ?
            WHERE slave_session_id = ? AND user_uuid = ?
        """, (status, slave_session_id, user_uuid))

        conn.commit()
        conn.close()

        app_logger.debug(f"Updated genie child session {slave_session_id} status to {status}")
        return True

    except Exception as e:
        app_logger.error(f"Failed to update genie child status: {e}", exc_info=True)
        return False
