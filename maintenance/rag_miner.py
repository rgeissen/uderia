"""
RAG Miner: Batch processor for historical session data.

This script processes historical session data and populates the RAG system
using the same logic as the real-time worker. It supports:
- Full reprocessing with --force flag
- Incremental updates
- Consistent with real-time processing logic including:
  * user_feedback_score initialization (default: 0)
  * Skipping conversational turns
  * Champion selection based on feedback + token efficiency

Note: The miner doesn't save case_id back to sessions since it runs offline
without user context. This is acceptable for batch processing.
"""

import os
import json
import glob
import logging
import argparse
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone
import uuid
from collections import defaultdict

# Add project root to path for imports
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# --- Import asyncio and RAGRetriever ---
import asyncio
from trusted_data_agent.agent.rag_retriever import RAGRetriever
from trusted_data_agent.core.config import APP_STATE, APP_CONFIG
from trusted_data_agent.core.config_manager import get_config_manager

# Configure a dedicated logger for the miner
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("rag_miner")

class SessionMiner:
    def __init__(self, sessions_dir: str | Path, output_dir: str | Path, force_reprocess: bool = False, rebuild_only: bool = False):
        self.sessions_dir = Path(sessions_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.force_reprocess = force_reprocess
        self.rebuild_only = rebuild_only
        
        if not rebuild_only and not self.sessions_dir.exists():
             logger.error(f"Sessions directory not found at: {self.sessions_dir}")
             
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # --- MODIFICATION START: Remove RAGRetriever initialization from __init__ ---
        self.retriever = None # Will be initialized inside run()
        # --- MODIFICATION END ---

    # --- MODIFICATION START: Refactor run() to be async and use RAGRetriever ---
    async def run(self):
        """
        Main entry point to scan and process all sessions. It feeds all
        historical turns into the RAGRetriever's processing method to
        ensure logic is 100% consistent with the real-time worker.
        """
        logger.info("Starting mining process.")
        logger.info(f"Input (Sessions): {self.sessions_dir}")
        logger.info(f"Output (Cases):   {self.output_dir}")

        # --- MODIFICATION START: Correct project root calculation ---
        # This script is at docs/RAG/rag_miner.py, so we need to go up 2 levels
        project_root = Path(__file__).resolve().parent.parent.parent
        # Hardcode path to chromadb cache
        chroma_cache_dir = project_root / ".chromadb_rag_cache"
        # --- MODIFICATION END ---

        if self.force_reprocess:
            logger.info("Force reprocess is enabled. Backing up feedback scores before clearing...")
            
            # Backup existing feedback scores from all collection directories
            feedback_backup = {}
            for collection_dir in self.output_dir.glob("collection_*"):
                if collection_dir.is_dir():
                    for old_case in collection_dir.glob("case_*.json"):
                        try:
                            with open(old_case, 'r', encoding='utf-8') as f:
                                case_data = json.load(f)
                            case_id = case_data.get('case_id')
                            feedback_score = case_data.get('metadata', {}).get('user_feedback_score', 0)
                            if feedback_score != 0:  # Only backup non-zero feedback
                                feedback_backup[case_id] = feedback_score
                                logger.info(f"Backed up feedback for case {case_id}: {feedback_score}")
                        except Exception as e:
                            logger.warning(f"Failed to backup feedback from {old_case.name}: {e}")
            
            logger.info(f"Backed up {len(feedback_backup)} feedback scores")
            
            # Clear all collection directories
            for collection_dir in self.output_dir.glob("collection_*"):
                if collection_dir.is_dir():
                    for old_case in collection_dir.glob("case_*.json"):
                        old_case.unlink()
                    # Remove empty collection directory
                    try:
                        collection_dir.rmdir()
                    except OSError:
                        pass  # Directory not empty, that's fine
            
            if chroma_cache_dir.exists():
                logger.info(f"Flushing ChromaDB cache at {chroma_cache_dir}...")
                shutil.rmtree(chroma_cache_dir)
            
            # Store feedback backup for restoration
            self.feedback_backup = feedback_backup
        else:
            self.feedback_backup = {}
        
        # --- MODIFICATION START: Load configuration and initialize retriever ---
        # Load RAG collections and MCP server configuration
        config_manager = get_config_manager()
        APP_STATE["rag_collections"] = config_manager.get_rag_collections()
        APP_CONFIG.CURRENT_MCP_SERVER_ID = config_manager.get_active_mcp_server_id()
        
        logger.info(f"Loaded configuration:")
        logger.info(f"  MCP Server ID: {APP_CONFIG.CURRENT_MCP_SERVER_ID}")
        logger.info(f"  RAG Collections: {len(APP_STATE.get('rag_collections', []))}")
        
        # Initialize the single RAGRetriever instance that this miner will use.
        self.retriever = RAGRetriever(
            rag_cases_dir=self.output_dir,
            embedding_model_name="all-MiniLM-L6-v2",
            persist_directory=project_root / ".chromadb_rag_cache"
        )
        logger.info(f"Miner initialized RAGRetriever with {len(self.retriever.collections)} active collection(s).")
        # --- MODIFICATION END ---

        # --- NEW: Rebuild-only mode ---
        if self.rebuild_only:
            logger.info("--- REBUILD MODE: Loading ChromaDB from existing JSON case files ---")
            collection_ids = list(self.retriever.collections.keys())
            if not collection_ids:
                logger.warning("No active collections found. Enable collections in tda_config.json first.")
                return
            
            for collection_id in collection_ids:
                logger.info(f"Rebuilding collection {collection_id}...")
                self.retriever._maintain_vector_store(collection_id)
            
            logger.info("Rebuild complete!")
            return
        # --- END REBUILD MODE ---

        session_files = list(self.sessions_dir.rglob("*.json"))
        logger.info(f"Found {len(session_files)} potential session files.")

        total_turns = 0
        processed_turns = 0

        logger.info("--- Processing all historical turns ---")
        for session_file in session_files:
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)

                if "id" not in session_data or "last_turn_data" not in session_data:
                    continue

                session_id = session_data["id"]
                workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

                for turn in workflow_history:
                    total_turns += 1
                    if not turn.get("isValid", True) or turn.get("turn") is None:
                        continue
                    
                    # The turn_summary *is* the turn object.
                    # We just need to ensure session_id is on it for the extractor.
                    if "session_id" not in turn:
                        turn["session_id"] = session_id
                    
                    # Note: We don't add user_uuid since the miner runs offline
                    # and doesn't have access to user context. The case_id won't
                    # be saved back to sessions, but that's acceptable for batch processing.
                    
                    # Call the same transactional logic as the real-time worker
                    case_id = await self.retriever.process_turn_for_rag(turn)
                    if case_id:
                        processed_turns += 1
                        logger.debug(f"Processed turn {turn.get('turn')} from session {session_id[:8]}... -> case {case_id[:8]}...")

            except Exception as e:
                logger.error(f"Failed to process session file {session_file.name}: {e}", exc_info=True)
        
        logger.info(f"Mining complete. Total turns scanned: {total_turns}. Turns processed: {processed_turns}.")
    # --- MODIFICATION END ---

    # --- MODIFICATION START: Remove redundant helper methods ---
    # _extract_case_study and _save_case_study are no longer needed here.
    # All logic is now centralized in RAGRetriever.
    # --- MODIFICATION END ---

if __name__ == '__main__':
    # --- MODIFICATION START: Correct project root and default path logic ---
    # SCRIPT_DIR is .../uderia/maintenance
    SCRIPT_DIR = Path(__file__).resolve().parent 
    # PROJECT_ROOT is .../uderia (go up 1 level)
    PROJECT_ROOT = SCRIPT_DIR.parent
    # Use the correct, original default paths
    DEFAULT_SESSIONS_DIR = PROJECT_ROOT / "tda_sessions"
    DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "rag" / "tda_rag_cases"
    # --- MODIFICATION END ---

    parser = argparse.ArgumentParser(description="Extract RAG case studies from TDA session logs or rebuild ChromaDB from existing cases.")
    parser.add_argument("--sessions_dir", type=str, default=str(DEFAULT_SESSIONS_DIR), 
                        help=f"Path to input sessions directory (default: {DEFAULT_SESSIONS_DIR})")
    parser.add_argument("--output_dir", type=str, default=str(DEFAULT_OUTPUT_DIR), 
                        help=f"Path to output case studies directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--force", action="store_true", help="Force reprocessing of all turns.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild ChromaDB from existing JSON case files (skips session processing).")

    args = parser.parse_args()

    # --- MODIFICATION START: Run the async main function ---
    miner = SessionMiner(args.sessions_dir, args.output_dir, force_reprocess=args.force, rebuild_only=args.rebuild)
    asyncio.run(miner.run())
    # --- MODIFICATION END ---