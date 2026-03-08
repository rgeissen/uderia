"""
Centralized RAG Efficiency Tracker

Tracks iterative improvements across all sessions in real-time.
Calculates token savings by comparing each turn to its predecessor within a session.
"""

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("efficiency_tracker")


class EfficiencyTracker:
    """
    Centralized tracker for RAG efficiency metrics across all sessions.
    
    Tracks:
    - Sequential improvements: Turn N vs Turn N-1 within same session
    - Cumulative token savings across all sessions
    - Cost savings based on actual model pricing
    """
    
    def __init__(self, state_file: Optional[Path] = None):
        """
        Initialize the efficiency tracker.
        
        Args:
            state_file: Path to persistent state file (default: tda_sessions/efficiency_state.json)
        """
        self.state_file = state_file or Path("tda_sessions/efficiency_state.json")
        self.lock = Lock()
        self.state = self._load_state()
        
    def _load_state(self) -> Dict[str, Any]:
        """Load state from disk or initialize new state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load efficiency state: {e}")
        
        # Initialize new state
        return {
            "total_output_tokens_saved": 0,
            "total_rag_improvements": 0,
            "total_sessions_tracked": 0,
            "cumulative_cost_saved": 0.0,
            "last_updated": None,
            "session_improvements": {},  # session_id -> list of improvements
            "user_metrics": {}  # user_uuid -> per-user metrics
        }
    
    def _save_state(self):
        """Persist state to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            # Convert sets to lists for JSON serialization
            serializable_state = self._prepare_for_serialization(self.state)
            with open(self.state_file, 'w') as f:
                json.dump(serializable_state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save efficiency state: {e}")
    
    def _prepare_for_serialization(self, obj):
        """Convert sets to lists recursively for JSON serialization."""
        if isinstance(obj, dict):
            return {k: self._prepare_for_serialization(v) for k, v in obj.items()}
        elif isinstance(obj, set):
            return list(obj)
        elif isinstance(obj, list):
            return [self._prepare_for_serialization(item) for item in obj]
        return obj
    
    def record_improvement(
        self, 
        session_id: str,
        turn_index: int,
        previous_output_tokens: int,
        current_output_tokens: int,
        had_rag: bool,
        cost_per_output_token: float = 0.0,
        user_uuid: Optional[str] = None
    ):
        """
        Record an improvement when a turn produces fewer output tokens than predecessor.
        
        Args:
            session_id: Unique session identifier
            turn_index: Index of current turn (0-based)
            previous_output_tokens: Output tokens from Turn N-1
            current_output_tokens: Output tokens from Turn N
            had_rag: Whether Turn N used RAG guidance
            cost_per_output_token: Cost per output token for this model
            user_uuid: User identifier for per-user tracking
        """
        with self.lock:
            # Calculate improvement
            if previous_output_tokens > 0:
                tokens_saved = previous_output_tokens - current_output_tokens
                cost_saved = tokens_saved * cost_per_output_token
                
                # Only count as improvement if RAG was used AND tokens decreased
                if had_rag and tokens_saved > 0:
                    self.state["total_output_tokens_saved"] += tokens_saved
                    self.state["total_rag_improvements"] += 1
                    self.state["cumulative_cost_saved"] += cost_saved
                    
                    # Track per-session improvements
                    if session_id not in self.state["session_improvements"]:
                        self.state["session_improvements"][session_id] = []
                        self.state["total_sessions_tracked"] += 1
                    
                    self.state["session_improvements"][session_id].append({
                        "turn_index": turn_index,
                        "tokens_saved": tokens_saved,
                        "cost_saved": cost_saved,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
                    # Track per-user metrics
                    if user_uuid:
                        if "user_metrics" not in self.state:
                            self.state["user_metrics"] = {}
                        
                        if user_uuid not in self.state["user_metrics"]:
                            self.state["user_metrics"][user_uuid] = {
                                "tokens_saved": 0,
                                "improvements": 0,
                                "cost_saved": 0.0,
                                "sessions": set()
                            }
                        
                        user_data = self.state["user_metrics"][user_uuid]
                        user_data["tokens_saved"] += tokens_saved
                        user_data["improvements"] += 1
                        user_data["cost_saved"] += cost_saved
                        if isinstance(user_data["sessions"], set):
                            user_data["sessions"].add(session_id)
                        else:
                            user_data["sessions"] = {session_id}
                    
                    self.state["last_updated"] = datetime.utcnow().isoformat()
                    self._save_state()
                    
                    logger.info(
                        f"Recorded improvement: session={session_id[:8]}, turn={turn_index}, "
                        f"saved={tokens_saved} tokens (${cost_saved:.4f})"
                    )
    
    def get_metrics(self, user_uuid: Optional[str] = None) -> Dict[str, Any]:
        """
        Get current efficiency metrics.
        
        Args:
            user_uuid: If provided, returns metrics for specific user only
        
        Returns:
            Dict with cumulative metrics:
            - total_output_tokens_saved
            - total_rag_improvements
            - cumulative_cost_saved
            - avg_tokens_saved_per_improvement
        """
        with self.lock:
            # Return per-user metrics if requested
            if user_uuid and "user_metrics" in self.state and user_uuid in self.state["user_metrics"]:
                user_data = self.state["user_metrics"][user_uuid]
                avg_saved = (
                    user_data["tokens_saved"] / user_data["improvements"]
                    if user_data["improvements"] > 0
                    else 0
                )
                
                # Handle sets for JSON serialization
                sessions_count = len(user_data["sessions"]) if isinstance(user_data["sessions"], (set, list)) else 0
                
                return {
                    "total_output_tokens_saved": user_data["tokens_saved"],
                    "total_rag_improvements": user_data["improvements"],
                    "total_sessions_tracked": sessions_count,
                    "cumulative_cost_saved": round(user_data["cost_saved"], 4),
                    "avg_tokens_saved_per_improvement": round(avg_saved, 1),
                    "last_updated": self.state.get("last_updated")
                }
            
            # Return global metrics
            avg_saved = (
                self.state["total_output_tokens_saved"] / self.state["total_rag_improvements"]
                if self.state["total_rag_improvements"] > 0
                else 0
            )
            
            return {
                "total_output_tokens_saved": self.state["total_output_tokens_saved"],
                "total_rag_improvements": self.state["total_rag_improvements"],
                "total_sessions_tracked": self.state["total_sessions_tracked"],
                "cumulative_cost_saved": round(self.state["cumulative_cost_saved"], 4),
                "avg_tokens_saved_per_improvement": round(avg_saved, 1),
                "last_updated": self.state["last_updated"]
            }
    
    def reset(self):
        """Reset all metrics (for testing or maintenance)."""
        with self.lock:
            self.state = {
                "total_output_tokens_saved": 0,
                "total_rag_improvements": 0,
                "total_sessions_tracked": 0,
                "cumulative_cost_saved": 0.0,
                "last_updated": None,
                "session_improvements": {}
            }
            self._save_state()
            logger.info("Efficiency tracker reset")


# Global singleton instance
_efficiency_tracker: Optional[EfficiencyTracker] = None


def get_efficiency_tracker() -> EfficiencyTracker:
    """Get the global efficiency tracker instance."""
    global _efficiency_tracker
    if _efficiency_tracker is None:
        _efficiency_tracker = EfficiencyTracker()
    return _efficiency_tracker
