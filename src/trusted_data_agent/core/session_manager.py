# src/trusted_data_agent/core/session_manager.py
import uuid
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path # Use pathlib for better path handling
import shutil # For potential cleanup later if needed
import asyncio # For sending notifications asynchronously
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
        app_logger.info(f"Session directory ensured at: {SESSIONS_DIR}")
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

        async with aiofiles.open(session_path, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(session_data, indent=2)) # Use indent for readability
        app_logger.debug(f"Successfully saved session '{session_id}' for user '{user_uuid}'.")

        # --- MODIFICATION START: Send session_model_update notification (with deduplication) ---
        notification_queues = APP_STATE.get("notification_queues", {}).get(user_uuid, set())
        if notification_queues:
            # Check if notification state has changed
            current_state = {
                "provider": session_data.get("provider"),
                "model": session_data.get("model"),
                "profile_tag": session_data.get("profile_tag"),
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

async def get_all_sessions(user_uuid: str) -> list[dict]:
    from trusted_data_agent.core.config import APP_CONFIG

    app_logger.debug(f"Getting all sessions for user '{user_uuid}'. Filter by user: {APP_CONFIG.SESSIONS_FILTER_BY_USER}")
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
                return []
        scan_dirs = [user_session_dir]
    else:
        # All users mode: scan all subdirectories
        app_logger.debug(f"Scanning all user directories in: {SESSIONS_DIR}")
        if not SESSIONS_DIR.is_dir():
            app_logger.warning(f"Sessions directory not found: {SESSIONS_DIR}. Returning empty list.")
            return []
        scan_dirs = [d for d in SESSIONS_DIR.iterdir() if d.is_dir()]

    # Scan all determined directories (recursively to include child Genie sessions)
    for session_dir in scan_dirs:
        for session_file in session_dir.glob("**/*.json"):
            app_logger.debug(f"Found potential session file: {session_file.name}")
            try:
                async with aiofiles.open(session_file, 'r', encoding='utf-8') as f:
                    # Load only necessary fields for summary to improve performance
                    content = await f.read()
                    data = json.loads(content)
                    
                    genie_metadata = data.get("genie_metadata", {})

                    # Enrich genie_metadata with nesting_level and slave_profile_tag from database
                    if genie_metadata.get("is_genie_slave"):
                        session_id = data.get("id", session_file.stem)
                        app_logger.info(f"[Nesting Debug] Session {session_id} is a genie slave, fetching parent link for user {user_uuid}...")
                        parent_link = await get_genie_parent_session(session_id, user_uuid)
                        app_logger.info(f"[Nesting Debug] Parent link data: {parent_link}")
                        if parent_link:
                            nesting_level = parent_link.get("nesting_level", 0)
                            slave_profile_tag = parent_link.get("slave_profile_tag")
                            genie_metadata["nesting_level"] = nesting_level
                            genie_metadata["slave_profile_tag"] = slave_profile_tag
                            app_logger.info(f"[Nesting Debug] Enriched session {session_id} with nesting_level={nesting_level}, slave_profile_tag={slave_profile_tag}")
                        else:
                            app_logger.warning(f"[Nesting Debug] No parent link found for session {session_id}")

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
    app_logger.debug(f"[FINAL RESULT] Returning {len(session_summaries)} sessions")
    for i, session in enumerate(session_summaries[:10], 1):
        session_id = session.get("id", "unknown")[:12]
        is_slave = session.get("genie_metadata", {}).get("is_genie_slave", False)
        nesting_level = session.get("genie_metadata", {}).get("nesting_level", "N/A")
        name = session.get("name", "Unnamed")[:30]
        app_logger.debug(f"[FINAL] {i}. {session_id}... - {name} (slave={is_slave}, level={nesting_level})")

    return session_summaries

async def delete_session(user_uuid: str, session_id: str) -> bool:
    """Archives a session by marking it as archived instead of deleting the file."""
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
            session_data["archived_at"] = datetime.now(timezone.utc).isoformat()

            # Save back to file
            async with aiofiles.open(session_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(session_data, indent=2, ensure_ascii=False))
            
            app_logger.info(f"Successfully archived session file: {session_path}")
            return True # Indicate success
        else:
            # This case should ideally not be hit if _find_session_path is correct
            app_logger.warning(f"Session file not found for archiving: {session_path}. Treating as success (already gone).")
            return True # Indicate success (idempotent delete)
    except (OSError, json.JSONDecodeError) as e:
        app_logger.error(f"Error archiving session file '{session_path}': {e}", exc_info=True)
        return False # Indicate failure due to error

# --- MODIFICATION START: Rename and refactor add_to_history ---
async def add_message_to_histories(user_uuid: str, session_id: str, role: str, content: str, html_content: str | None = None, source: str | None = None, profile_tag: str | None = None, is_session_primer: bool = False):
    """
    Adds a message to the appropriate histories, decoupling UI from LLM context.
    - `content` (plain text) is *always* added to the LLM's chat_object.
    - `html_content` (if provided) is added to the UI's session_history.
    - If `html_content` is not provided, `content` is used for the UI.
    - `profile_tag` (if provided) stores which profile was used for this message.
    - `is_session_primer` (if True) marks this message as part of session initialization.
    """
    session_data = await _load_session(user_uuid, session_id)
    if session_data:
        # --- 1. Add to UI History (session_history) ---
        # Use the rich HTML content if provided, otherwise fall back to plain text.
        ui_content = html_content if html_content is not None else content
        
        # --- MODIFICATION START: Explicitly manage turn_number ---
        session_history = session_data.setdefault('session_history', [])
        
        # Determine the next turn number
        next_turn_number = 1
        if session_history:
            last_message = session_history[-1]
            last_turn_number = last_message.get('turn_number', 0) # Default to 0 if not found
            # Increment turn number only when a new user message is added
            if role == 'user':
                next_turn_number = last_turn_number + 1
            else: # Assistant's turn
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
        
        session_history.append(message_to_append)
        # --- MODIFICATION END ---

        # --- 2. Add to LLM History (chat_object) ---
        # Determine the correct role for the LLM provider
        provider_in_session = session_data.get("license_info", {}).get("provider")
        current_provider = APP_CONFIG.CURRENT_PROVIDER
        provider = provider_in_session or current_provider
        if not provider:
             app_logger.warning(f"Could not determine LLM provider for role conversion in session {session_id}. Defaulting role.")
             provider = "Unknown" # Avoid error if APP_CONFIG isn't set somehow

        llm_role = 'model' if role == 'assistant' and provider == 'Google' else role
        
        # --- MODIFICATION START: Explicitly manage turn_number for chat_object ---
        chat_object_history = session_data.setdefault('chat_object', [])

        # Determine the next turn number for the LLM history
        llm_turn_number = 1
        if chat_object_history:
            last_llm_message = chat_object_history[-1]
            last_llm_turn = last_llm_message.get('turn_number', 0) # Default to 0
            # Increment only on the user's turn for the next cycle
            if llm_role == 'user':
                llm_turn_number = last_llm_turn + 1
            else: # Model's turn
                llm_turn_number = last_llm_turn

        # *Always* add the clean, plain text `content` to the LLM's history.
        chat_object_history.append({
            'role': llm_role,
            'content': content,
            'isValid': True,
            'turn_number': llm_turn_number
        })
        # --- MODIFICATION END ---
        # --- MODIFICATION END ---

        if not await _save_session(user_uuid, session_id, session_data):
             app_logger.error(f"Failed to save session after adding history for {session_id}")
    else:
        app_logger.warning(f"Could not add history: Session {session_id} not found for user {user_uuid}.")

async def update_session_name(user_uuid: str, session_id: str, new_name: str):
    session_data = await _load_session(user_uuid, session_id)
    if session_data:
        session_data['name'] = new_name
        if not await _save_session(user_uuid, session_id, session_data):
             app_logger.error(f"Failed to save session after updating name for {session_id}")
        else:
            # --- CONSUMPTION TRACKING: Update session name in database ---
            try:
                from trusted_data_agent.auth.database import get_db_session
                from trusted_data_agent.auth.consumption_manager import ConsumptionManager
                
                with get_db_session() as db_session:
                    manager = ConsumptionManager(db_session)
                    manager.update_session_name(user_uuid, session_id, new_name)
            except Exception as e:
                app_logger.warning(f"Failed to update session name in consumption database: {e}")
            # --- CONSUMPTION TRACKING END ---
            
            # --- MODIFICATION START: Send session_name_update notification ---
            notification_queues = APP_STATE.get("notification_queues", {}).get(user_uuid, set())
            if notification_queues:
                notification_payload = {
                    "session_id": session_id,
                    "newName": new_name,
                }
                app_logger.debug(f"update_session_name sending notification for session {session_id}: newName={new_name}")
                notification = {
                    "type": "session_name_update",
                    "payload": notification_payload
                }
                for queue in notification_queues:
                    asyncio.create_task(queue.put(notification))
            # --- MODIFICATION END ---
    else:
         app_logger.warning(f"Could not update name: Session {session_id} not found for user {user_uuid}.")


async def update_token_count(user_uuid: str, session_id: str, input_tokens: int, output_tokens: int):
    """Updates the token counts for a given session."""
    session_data = await _load_session(user_uuid, session_id)
    if session_data:
        session_data['input_tokens'] = session_data.get('input_tokens', 0) + input_tokens
        session_data['output_tokens'] = session_data.get('output_tokens', 0) + output_tokens
        if not await _save_session(user_uuid, session_id, session_data):
            app_logger.error(f"Failed to save session after updating tokens for {session_id}")
        
        # Record token usage for consumption tracking and quota enforcement
        try:
            from trusted_data_agent.auth.token_quota import record_token_usage
            record_token_usage(user_uuid, input_tokens, output_tokens)
            app_logger.debug(f"Recorded token usage for user {user_uuid}: input={input_tokens}, output={output_tokens}")
        except Exception as e:
            app_logger.error(f"Failed to record token usage for user {user_uuid}: {e}")
        
        # --- CONSUMPTION TRACKING START ---
        # Dual-write to consumption database for performance optimization
        # This enables O(1) lookups for rate limiting and quota checks
        try:
            from trusted_data_agent.auth.database import get_db_session
            from trusted_data_agent.auth.consumption_manager import ConsumptionManager
            
            # Note: This is a lightweight update - no full turn data yet
            # Full turn metrics will be recorded in update_last_turn_data
            with get_db_session() as db_session:
                manager = ConsumptionManager(db_session)
                # Just increment request counter here (called at start of turn)
                manager.increment_request_counter(user_uuid)
                app_logger.debug(f"Incremented request counter for user {user_uuid}")
        except Exception as e:
            # Non-critical: File storage is source of truth, DB is performance cache
            app_logger.warning(f"Failed to update consumption tracking for user {user_uuid}: {e}")
        # --- CONSUMPTION TRACKING END ---
    else:
        app_logger.warning(f"Could not update tokens: Session {session_id} not found for user {user_uuid}.")


async def update_models_used(user_uuid: str, session_id: str, provider: str, model: str, profile_tag: str | None = None):
    """Adds the current model/profile to the list used in the session."""
    app_logger.debug(f"update_models_used called for session {session_id} with provider={provider}, model={model}, profile_tag={profile_tag}")
    session_data = await _load_session(user_uuid, session_id)
    if session_data:
        # Keep models_used for backwards compatibility
        models_used = session_data.get('models_used', [])
        model_string = f"{provider}/{model}"
        if model_string not in models_used:
            models_used.append(model_string)
            session_data['models_used'] = models_used

        # Add profile tag to profile_tags_used
        if profile_tag:
            profile_tags_used = session_data.get('profile_tags_used', [])
            if profile_tag not in profile_tags_used:
                profile_tags_used.append(profile_tag)
                session_data['profile_tags_used'] = profile_tags_used

        # --- MODIFICATION START: Update top-level fields ---
        app_logger.debug(f"Updating session_data provider from {session_data.get('provider')} to {provider}")
        app_logger.debug(f"Updating session_data model from {session_data.get('model')} to {model}")
        app_logger.debug(f"Updating session_data profile_tag from {session_data.get('profile_tag')} to {profile_tag}")
        session_data['provider'] = provider
        session_data['model'] = model
        session_data['profile_tag'] = profile_tag
        # --- MODIFICATION END ---

        if not await _save_session(user_uuid, session_id, session_data):
            app_logger.error(f"Failed to save session after updating models used for {session_id}")
    else:
        app_logger.warning(f"Could not update models used: Session {session_id} not found for user {user_uuid}.")


async def update_last_turn_data(user_uuid: str, session_id: str, turn_data: dict):
    """Saves the most recent turn's action history and plans to the session file."""
    session_data = await _load_session(user_uuid, session_id)
    if session_data:
        # Ensure the structure exists (already done on creation, but good for robustness)
        if "last_turn_data" not in session_data:
            session_data["last_turn_data"] = {}
        if "workflow_history" not in session_data["last_turn_data"] or not isinstance(session_data["last_turn_data"]["workflow_history"], list):
            session_data["last_turn_data"]["workflow_history"] = []
        
        # --- MODIFICATION START: Add isValid=True for new turns ---
        # By default, all new turns are valid.
        if isinstance(turn_data, dict):
            turn_data["isValid"] = True
        # --- MODIFICATION END ---

        # --- EFFICIENCY TRACKING START ---
        # Track sequential improvements: compare Turn N vs Turn N-1
        # Credit RAG when PREVIOUS turn had RAG guidance (teaching effect)
        workflow_history = session_data["last_turn_data"]["workflow_history"]
        if len(workflow_history) > 0 and isinstance(turn_data, dict):
            previous_turn = workflow_history[-1]
            previous_output = previous_turn.get('turn_output_tokens', 0)
            current_output = turn_data.get('turn_output_tokens', 0)
            # Check if PREVIOUS turn had RAG (enables improvement in current turn)
            previous_had_rag = previous_turn.get('rag_source_collection_id') is not None
            
            # Calculate cost per token for this model
            provider = turn_data.get('provider', 'Unknown')
            model = turn_data.get('model', 'unknown')
            output_tokens = turn_data.get('turn_output_tokens', 0)
            
            cost_per_token = 0.0
            if output_tokens > 0:
                from trusted_data_agent.core.cost_manager import get_cost_manager
                cost_manager = get_cost_manager()
                turn_cost = cost_manager.calculate_cost(provider, model, 0, output_tokens)
                cost_per_token = turn_cost / output_tokens if output_tokens > 0 else 0.0
            
            # Record improvement if PREVIOUS turn had RAG and current turn improved
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

                # FIX: Store efficiency gain in turn_data for consumption database sync
                # Credit the CURRENT turn if it used RAG and resulted in fewer output tokens
                current_turn_has_rag = turn_data.get('rag_source_collection_id') is not None
                if current_turn_has_rag and current_output < previous_output:
                    tokens_saved = previous_output - current_output
                    turn_data['rag_efficiency_gain'] = tokens_saved
                    app_logger.debug(f"RAG efficiency gain for current turn: {tokens_saved} tokens saved")
        # --- EFFICIENCY TRACKING END ---

        # Append the new turn data (contains original_plan and user_query now)
        session_data["last_turn_data"]["workflow_history"].append(turn_data)

        # --- CONSUMPTION TRACKING START ---
        # Record full turn metrics to consumption database
        # This provides comprehensive per-turn tracking with cost, RAG, quality metrics
        try:
            from trusted_data_agent.auth.database import get_db_session
            from trusted_data_agent.auth.consumption_manager import ConsumptionManager
            from trusted_data_agent.core.cost_manager import get_cost_manager
            
            with get_db_session() as db_session:
                manager = ConsumptionManager(db_session)
                
                # Extract turn metrics
                turn_number = len(session_data["last_turn_data"]["workflow_history"])
                input_tokens = turn_data.get('turn_input_tokens', 0)
                output_tokens = turn_data.get('turn_output_tokens', 0)
                provider = turn_data.get('provider', 'Unknown')
                model = turn_data.get('model', 'unknown')
                status = turn_data.get('status', 'success')
                
                # RAG metrics
                rag_used = turn_data.get('rag_source_collection_id') is not None
                rag_tokens_saved = turn_data.get('rag_efficiency_gain', 0) if rag_used else 0
                
                # Calculate cost
                cost_manager = get_cost_manager()
                cost_usd = cost_manager.calculate_cost(provider, model, input_tokens, output_tokens)
                cost_usd_cents = int(cost_usd * 1000000)  # Convert to micro-dollars
                app_logger.info(f"[Cost Tracking] {provider}/{model}: {input_tokens}in + {output_tokens}out = ${cost_usd:.6f} ({cost_usd_cents} micro-dollars)")

                # Reload session to get latest name (might have been updated after initial load)
                current_session = await _load_session(user_uuid, session_id)
                session_name = (current_session.get('name') if current_session else None) or session_data.get('name') or 'Untitled Session'
                user_query = turn_data.get('user_query', '')
                
                # Record the turn
                manager.record_turn(
                    user_id=user_uuid,
                    session_id=session_id,
                    turn_number=turn_number,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    provider=provider,
                    model=model,
                    status=status,
                    rag_used=rag_used,
                    rag_tokens_saved=rag_tokens_saved,
                    cost_usd_cents=cost_usd_cents,
                    user_query=user_query,
                    session_name=session_name
                )
                
                app_logger.debug(f"Recorded turn with session_name='{session_name}', user_query='{user_query[:50] if user_query else None}...')")
                
                app_logger.debug(f"Recorded turn metrics for user {user_uuid}, session {session_id}, turn {turn_number}")
        except Exception as e:
            # Non-critical: File storage is source of truth, DB is performance cache
            app_logger.warning(f"Failed to record turn metrics for user {user_uuid}: {e}")
        # --- CONSUMPTION TRACKING END ---

        if not await _save_session(user_uuid, session_id, session_data):
            app_logger.error(f"Failed to save session after updating last turn data for {session_id}")
    else:
        app_logger.warning(f"Could not update last turn data: Session {session_id} not found for user {user_uuid}.")

# --- MODIFICATION START: Add function to purge only the agent's memory ---
async def purge_session_memory(user_uuid: str, session_id: str) -> bool:
    """
    Resets the agent's LLM context memory (`chat_object`) for a session,
    but leaves the UI history (`session_history`) and plan/trace history
    (`last_turn_data`) intact.
    """
    app_logger.info(f"Attempting to purge agent memory (chat_object) for session '{session_id}', user '{user_uuid}'.")
    session_data = await _load_session(user_uuid, session_id)
    if not session_data:
        app_logger.warning(f"Could not purge memory: Session {session_id} not found for user {user_uuid}.")
        return False # Session not found

    try:
        # --- MODIFICATION START: Mark all existing history as invalid ---
        # This makes the "purge" a persistent archival event.

        # 1. Mark UI history (session_history) as invalid
        session_history = session_data.get('session_history', [])
        history_count = 0
        if isinstance(session_history, list):
            for msg in session_history:
                if isinstance(msg, dict):
                    msg["isValid"] = False
                    history_count += 1
        
        # 2. Mark backend turn data (workflow_history) as invalid
        workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])
        turn_count = 0
        if isinstance(workflow_history, list):
            for turn in workflow_history:
                if isinstance(turn, dict):
                    turn["isValid"] = False
                    turn_count += 1
        
        app_logger.info(f"Marked {history_count} UI messages and {turn_count} turns as invalid for session '{session_id}'.")
        # --- MODIFICATION END ---

        # Determine the correct initial state for chat_object
        # This mirrors the logic in create_session
        chat_history_for_file = []
        provider_in_session = session_data.get("license_info", {}).get("provider")
        current_provider = APP_CONFIG.CURRENT_PROVIDER
        provider = provider_in_session or current_provider or "Google" # Default to Google logic if unknown

        if provider == "Google":
            initial_history_google = [
                {"role": "user", "parts": [{"text": "You are a helpful assistant."}]},
                {"role": "model", "parts": [{"text": "Understood."}]}
            ]
            chat_history_for_file = [{'role': m['role'], 'content': m['parts'][0]['text']} for m in initial_history_google]
        
        # Reset *only* the chat_object
        session_data['chat_object'] = chat_history_for_file
        
        # Also reset the full_context_sent flag so the agent sends the full system prompt next time
        session_data['full_context_sent'] = False

        app_logger.info(f"Successfully reset chat_object for session '{session_id}'. Invalidated existing history.")

        if not await _save_session(user_uuid, session_id, session_data):
            app_logger.error(f"Failed to save session after purging memory for {session_id}")
            return False # Save failed

        return True # Success

    except Exception as e:
        app_logger.error(f"An unexpected error occurred during memory purge for session '{session_id}': {e}", exc_info=True)
# --- MODIFICATION END ---

# --- MODIFICATION START: Add function to toggle turn validity ---
async def toggle_turn_validity(user_uuid: str, session_id: str, turn_id: int) -> bool:
    """
    Toggles the 'isValid' status of a specific turn and its corresponding
    UI messages in the session history and LLM chat_object.
    """
    app_logger.info(f"Toggling validity for turn {turn_id} in session '{session_id}' for user '{user_uuid}'.")
    session_data = await _load_session(user_uuid, session_id)
    if not session_data:
        app_logger.warning(f"Could not toggle validity: Session {session_id} not found.")
        return False

    try:
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
                    app_logger.info(f"Found turn {turn_id} in workflow_history. Set isValid to {new_status}.")
                    break

        if not turn_found:
            app_logger.warning(f"Turn {turn_id} not found in workflow_history for session {session_id}.")
            return False # If the planner's source of truth can't be updated, fail fast

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
                        app_logger.info(f"Updated messages in session_history for turn {turn_id} to isValid={new_status}.")
                        break

        # 3. Toggle validity in chat_object (for LLM context / Genie conversation history)
        chat_object = session_data.get('chat_object', [])
        if isinstance(chat_object, list):
            # Find messages with matching turn_number
            chat_updated = 0
            for msg in chat_object:
                if isinstance(msg, dict) and msg.get('turn_number') == turn_id:
                    msg['isValid'] = new_status
                    chat_updated += 1
            if chat_updated > 0:
                app_logger.info(f"Updated {chat_updated} messages in chat_object for turn {turn_id} to isValid={new_status}.")

        if not await _save_session(user_uuid, session_id, session_data):
            app_logger.error(f"Failed to save session after toggling validity for turn {turn_id}")
            return False

        return True

    except Exception as e:
        app_logger.error(f"An unexpected error occurred during validity toggle for turn {turn_id}: {e}", exc_info=True)
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

    try:
        session_data = await _load_session(user_uuid, session_id)
        if not session_data:
            app_logger.warning(f"Could not update feedback: Session {session_id} not found for user {user_uuid}.")
            return False

        # Get workflow_history from last_turn_data
        workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])
        
        # Find the turn with matching turn number
        turn_found = False
        case_id = None
        for turn in workflow_history:
            if turn.get("turn") == turn_id:
                # Update or remove feedback field
                if vote is None:
                    turn.pop("feedback", None)
                else:
                    turn["feedback"] = vote
                turn_found = True
                
                # Extract case_id if this turn has one (for RAG update)
                case_id = turn.get("case_id")
                
                app_logger.info(f"Updated feedback for turn {turn_id} in session {session_id}: {vote}")
                break
        
        if not turn_found:
            app_logger.warning(f"Turn {turn_id} not found in workflow_history for session {session_id}")
            return False

        # Save the updated session data
        if not await _save_session(user_uuid, session_id, session_data):
            app_logger.error(f"Failed to save session after updating feedback for turn {turn_id}")
            return False

        # --- Update RAG case if RAG is enabled and case_id exists ---
        if APP_CONFIG.RAG_ENABLED and case_id:
            retriever = APP_STATE.get('rag_retriever_instance')
            if retriever:
                # Convert vote string to numeric score
                feedback_score = 1 if vote == 'up' else -1 if vote == 'down' else 0
                
                # Update the RAG case asynchronously
                try:
                    # Get or create event loop
                    try:
                        loop = asyncio.get_running_loop()
                        # We're already in an async context
                        loop.create_task(retriever.update_case_feedback(case_id, feedback_score))
                    except RuntimeError:
                        # No running loop, create new one
                        asyncio.run(retriever.update_case_feedback(case_id, feedback_score))
                    
                    app_logger.info(f"Queued RAG case {case_id} feedback update: {feedback_score}")
                except Exception as e:
                    app_logger.error(f"Failed to update RAG case {case_id}: {e}", exc_info=True)
            else:
                app_logger.debug(f"RAG retriever not available, skipping case update for turn {turn_id}")
        
        return True

    except Exception as e:
        app_logger.error(f"Error updating feedback for turn {turn_id}: {e}", exc_info=True)
        return False
# --- MODIFICATION END ---

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
        session_data = await _load_session(user_uuid, session_id)
        if not session_data:
            app_logger.warning(f"Could not add case_id: Session {session_id} not found for user {user_uuid}.")
            return False

        # Get workflow_history from last_turn_data
        workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])
        
        # Find the turn with matching turn number
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

        # Save the updated session data
        if not await _save_session(user_uuid, session_id, session_data):
            app_logger.error(f"Failed to save session after adding case_id to turn {turn_id}")
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


async def cleanup_genie_slave_sessions(parent_session_id: str, user_uuid: str) -> bool:
    """
    Clean up (delete) all child sessions when a Genie parent session is deleted.

    Note: Function name preserved for API compatibility.

    Args:
        parent_session_id: The Genie coordinator session ID
        user_uuid: The user who owns the sessions

    Returns:
        True if successful, False otherwise
    """
    try:
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root

        # Get all child sessions
        slaves = await get_genie_slave_sessions(parent_session_id, user_uuid)

        # Delete each child session file
        for slave in slaves:
            slave_session_id = slave.get('slave_session_id')
            if slave_session_id:
                await delete_session(user_uuid, slave_session_id)
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
        return True

    except Exception as e:
        app_logger.error(f"Failed to cleanup genie child sessions: {e}", exc_info=True)
        return False


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
