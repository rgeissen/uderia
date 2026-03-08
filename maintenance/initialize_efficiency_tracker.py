#!/usr/bin/env python3
"""
Initialize Efficiency Tracker from Existing Sessions

Analyzes all historical session data and populates the efficiency tracker
with sequential improvements (Turn N vs Turn N-1) across all users.

Usage:
    python maintenance/initialize_efficiency_tracker.py
    python maintenance/initialize_efficiency_tracker.py --reset  # Reset before loading
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trusted_data_agent.core.efficiency_tracker import get_efficiency_tracker
from trusted_data_agent.core.cost_manager import get_cost_manager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_cost_per_token(provider: str, model: str, output_tokens: int) -> float:
    """Calculate cost per output token for a given model."""
    if output_tokens == 0:
        return 0.0
    
    cost_manager = get_cost_manager()
    total_cost = cost_manager.calculate_cost(provider, model, 0, output_tokens)
    return total_cost / output_tokens if output_tokens > 0 else 0.0


def process_session_file(session_file: Path, tracker, user_uuid: str = None) -> Dict[str, int]:
    """
    Process a single session file and record improvements.
    
    Args:
        session_file: Path to session JSON file
        tracker: Efficiency tracker instance
        user_uuid: User identifier for per-user tracking
    
    Returns:
        Dict with statistics for this session
    """
    stats = {
        "turns_processed": 0,
        "improvements_found": 0,
        "tokens_saved": 0
    }
    
    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
        
        # Extract session ID from filename
        session_id = session_file.stem
        
        # Get workflow history
        workflow_history = session_data.get('last_turn_data', {}).get('workflow_history', [])
        
        if len(workflow_history) < 2:
            return stats  # Need at least 2 turns to compare
        
        # Process each turn sequentially
        previous_turn = None
        for turn_index, turn in enumerate(workflow_history):
            if not turn.get('isValid', True):
                continue
            
            stats["turns_processed"] += 1
            
            # Skip first turn (no predecessor to compare)
            if previous_turn is None:
                previous_turn = turn
                continue
            
            # Get token counts
            previous_output = previous_turn.get('turn_output_tokens', 0)
            current_output = turn.get('turn_output_tokens', 0)
            # Check if PREVIOUS turn had RAG (enables improvement in current turn)
            previous_had_rag = previous_turn.get('rag_source_collection_id') is not None
            
            # Calculate cost per token
            provider = turn.get('provider', 'Unknown')
            model = turn.get('model', 'unknown')
            cost_per_token = calculate_cost_per_token(provider, model, current_output)
            
            # Record improvement if PREVIOUS turn had RAG and current turn improved
            if previous_had_rag and previous_output > 0 and current_output > 0:
                tokens_saved = previous_output - current_output
                if tokens_saved > 0:
                    tracker.record_improvement(
                        session_id=session_id,
                        turn_index=turn_index,
                        previous_output_tokens=previous_output,
                        current_output_tokens=current_output,
                        had_rag=previous_had_rag,
                        cost_per_output_token=cost_per_token,
                        user_uuid=user_uuid
                    )
                    stats["improvements_found"] += 1
                    stats["tokens_saved"] += tokens_saved
            
            previous_turn = turn
        
    except Exception as e:
        logger.warning(f"Error processing {session_file.name}: {e}")
    
    return stats


def main():
    """Main initialization routine."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Initialize efficiency tracker from existing sessions')
    parser.add_argument('--reset', action='store_true', help='Reset tracker before loading')
    parser.add_argument('--sessions-dir', default='tda_sessions', help='Path to sessions directory')
    args = parser.parse_args()
    
    logger.info("="*60)
    logger.info("Efficiency Tracker Initialization")
    logger.info("="*60)
    
    # Get tracker instance
    tracker = get_efficiency_tracker()
    
    # Reset if requested
    if args.reset:
        logger.info("Resetting efficiency tracker...")
        tracker.reset()
    
    # Scan all session directories
    sessions_base = Path(args.sessions_dir)
    if not sessions_base.exists():
        logger.error(f"Sessions directory not found: {sessions_base}")
        return 1
    
    # Find all user directories
    user_dirs = [d for d in sessions_base.iterdir() if d.is_dir() and not d.name.startswith('.')]
    logger.info(f"Found {len(user_dirs)} user directories")
    
    # Process all sessions
    total_stats = {
        "sessions_processed": 0,
        "turns_processed": 0,
        "improvements_found": 0,
        "tokens_saved": 0,
        "users_processed": 0
    }
    
    for user_dir in user_dirs:
        user_uuid = user_dir.name
        logger.info(f"\nProcessing user: {user_uuid[:8]}...")
        
        session_files = list(user_dir.glob('*.json'))
        logger.info(f"  Found {len(session_files)} session files")
        
        user_improvements = 0
        for session_file in session_files:
            stats = process_session_file(session_file, tracker, user_uuid=user_uuid)
            
            if stats["improvements_found"] > 0:
                logger.info(
                    f"    {session_file.name[:16]}... → "
                    f"{stats['improvements_found']} improvements, "
                    f"{stats['tokens_saved']} tokens saved"
                )
            
            total_stats["sessions_processed"] += 1
            total_stats["turns_processed"] += stats["turns_processed"]
            total_stats["improvements_found"] += stats["improvements_found"]
            total_stats["tokens_saved"] += stats["tokens_saved"]
            user_improvements += stats["improvements_found"]
        
        if user_improvements > 0:
            total_stats["users_processed"] += 1
            logger.info(f"  User total: {user_improvements} improvements")
    
    # Display final metrics
    logger.info("\n" + "="*60)
    logger.info("INITIALIZATION COMPLETE")
    logger.info("="*60)
    logger.info(f"Users processed:        {total_stats['users_processed']}")
    logger.info(f"Sessions processed:     {total_stats['sessions_processed']}")
    logger.info(f"Turns processed:        {total_stats['turns_processed']}")
    logger.info(f"Improvements found:     {total_stats['improvements_found']}")
    logger.info(f"Tokens saved:           {total_stats['tokens_saved']:,}")
    
    # Get final tracker metrics
    metrics = tracker.get_metrics()
    logger.info("\n" + "-"*60)
    logger.info("TRACKER METRICS:")
    logger.info("-"*60)
    logger.info(f"Total output tokens saved:  {metrics['total_output_tokens_saved']:,}")
    logger.info(f"Total RAG improvements:     {metrics['total_rag_improvements']}")
    logger.info(f"Total sessions tracked:     {metrics['total_sessions_tracked']}")
    logger.info(f"Cumulative cost saved:      ${metrics['cumulative_cost_saved']:.4f}")
    logger.info(f"Avg tokens saved/improve:   {metrics['avg_tokens_saved_per_improvement']:.1f}")
    logger.info(f"Last updated:               {metrics['last_updated']}")
    logger.info("="*60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
