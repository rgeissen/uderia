"""
Consumption tracking manager for real-time token usage and rate limiting.

This module provides high-performance consumption tracking with dual-write pattern:
- Primary: File-based session storage (source of truth)
- Secondary: Database consumption cache (performance optimization)

Design principles:
- O(1) lookups for rate limiting and quota checks
- Atomic updates to prevent race conditions
- Graceful degradation if DB is unavailable
- Periodic reconciliation with file-based source of truth
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import (
    UserConsumption, ConsumptionTurn, ConsumptionPeriodsArchive,
    User, ConsumptionProfile
)

logger = logging.getLogger(__name__)


class ConsumptionManager:
    """Manages user consumption tracking and enforcement."""
    
    def __init__(self, db_session: Session):
        """
        Initialize consumption manager.
        
        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session
    
    def get_or_create_consumption(self, user_id: str) -> UserConsumption:
        """
        Get or create consumption record for user.
        
        Args:
            user_id: User ID
            
        Returns:
            UserConsumption record (committed to DB)
        """
        consumption = self.db.query(UserConsumption).filter_by(user_id=user_id).first()
        
        if not consumption:
            # Get user and their consumption profile
            user = self.db.query(User).filter_by(id=user_id).first()
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            profile = user.consumption_profile
            if not profile:
                # Get default profile
                profile = self.db.query(ConsumptionProfile).filter_by(is_default=True).first()
            
            # Create new consumption record
            now = datetime.now(timezone.utc)
            current_period = now.strftime("%Y-%m")
            
            consumption = UserConsumption(
                user_id=user_id,
                current_period=current_period,
                period_started_at=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                hour_reset_at=now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1),
                day_reset_at=now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
                input_tokens_limit=profile.input_tokens_per_month if profile else None,
                output_tokens_limit=profile.output_tokens_per_month if profile else None,
                prompts_per_hour_limit=profile.prompts_per_hour if profile else 100,
                prompts_per_day_limit=profile.prompts_per_day if profile else 1000
            )
            
            self.db.add(consumption)
            self.db.commit()
            self.db.refresh(consumption)
            
            logger.info(f"Created consumption record for user {user_id}, period {current_period}")
        
        return consumption
    
    def check_rate_limits(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if user has exceeded rate limits.
        
        Args:
            user_id: User ID
            
        Returns:
            Tuple of (allowed: bool, reason: Optional[str])
        """
        consumption = self.get_or_create_consumption(user_id)
        now = datetime.now(timezone.utc)
        
        # Ensure reset times are timezone-aware for comparison
        # Handle both None and timezone-naive datetimes from database
        try:
            hour_reset = consumption.hour_reset_at
            if hour_reset and hour_reset.tzinfo is None:
                hour_reset = hour_reset.replace(tzinfo=timezone.utc)
                # Update the database record to be timezone-aware
                consumption.hour_reset_at = hour_reset
        except (TypeError, AttributeError):
            hour_reset = None
        
        try:
            day_reset = consumption.day_reset_at
            if day_reset and day_reset.tzinfo is None:
                day_reset = day_reset.replace(tzinfo=timezone.utc)
                # Update the database record to be timezone-aware
                consumption.day_reset_at = day_reset
        except (TypeError, AttributeError):
            day_reset = None
        
        # Reset hourly counter if needed
        if not hour_reset or now >= hour_reset:
            consumption.requests_this_hour = 0
            consumption.hour_reset_at = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        
        # Reset daily counter if needed
        if not day_reset or now >= day_reset:
            consumption.requests_today = 0
            consumption.day_reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        
        # Commit all changes at once
        self.db.commit()
        
        # Check hourly limit
        if consumption.requests_this_hour >= consumption.prompts_per_hour_limit:
            return False, f"Hourly limit exceeded ({consumption.prompts_per_hour_limit} requests/hour)"
        
        # Check daily limit
        if consumption.requests_today >= consumption.prompts_per_day_limit:
            return False, f"Daily limit exceeded ({consumption.prompts_per_day_limit} requests/day)"
        
        return True, None
    
    def check_token_quota(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if user has exceeded monthly token quota.
        
        Args:
            user_id: User ID
            
        Returns:
            Tuple of (allowed: bool, reason: Optional[str])
        """
        consumption = self.get_or_create_consumption(user_id)
        
        # Check input token quota
        if consumption.input_tokens_limit is not None:
            if consumption.total_input_tokens >= consumption.input_tokens_limit:
                return False, f"Input token quota exceeded ({consumption.input_tokens_limit} tokens/month)"
        
        # Check output token quota
        if consumption.output_tokens_limit is not None:
            if consumption.total_output_tokens >= consumption.output_tokens_limit:
                return False, f"Output token quota exceeded ({consumption.output_tokens_limit} tokens/month)"
        
        return True, None
    
    def increment_request_counter(self, user_id: str) -> None:
        """
        Increment request counters (hourly, daily, velocity).
        Call this at the START of each request.
        
        Args:
            user_id: User ID
        """
        consumption = self.get_or_create_consumption(user_id)
        now = datetime.now(timezone.utc)
        
        # Increment counters
        consumption.requests_this_hour += 1
        consumption.requests_today += 1
        
        # Update peak tracking
        if consumption.requests_this_hour > consumption.peak_requests_per_hour:
            consumption.peak_requests_per_hour = consumption.requests_this_hour
        
        if consumption.requests_today > consumption.peak_requests_per_day:
            consumption.peak_requests_per_day = consumption.requests_today
        
        consumption.last_updated_at = now
        self.db.commit()
    
    def record_turn(
        self,
        user_id: str,
        session_id: str,
        turn_number: int,
        input_tokens: int,
        output_tokens: int,
        provider: str,
        model: str,
        status: str,
        rag_used: bool = False,
        rag_tokens_saved: int = 0,
        cost_usd_cents: int = 0,
        user_query: str = None,
        session_name: str = None
    ) -> None:
        """
        Record a completed turn with full metrics.
        Call this at the END of each turn.
        
        Args:
            user_id: User ID
            session_id: Session ID
            turn_number: Turn number (1-indexed)
            input_tokens: Input token count
            output_tokens: Output token count
            provider: LLM provider name
            model: Model name
            status: Turn status (success, failure, partial)
            rag_used: Whether RAG was used
            rag_tokens_saved: Tokens saved by RAG efficiency
            cost_usd_cents: Cost in micro-dollars (USD × 1,000,000)
        """
        consumption = self.get_or_create_consumption(user_id)
        now = datetime.now(timezone.utc)
        
        # Update token counts
        total_tokens = input_tokens + output_tokens
        consumption.total_input_tokens += input_tokens
        consumption.total_output_tokens += output_tokens
        consumption.total_tokens += total_tokens
        
        # Update quality metrics
        consumption.total_turns += 1
        if status == "success":
            consumption.successful_turns += 1
        elif status == "failure":
            consumption.failed_turns += 1
        
        # Update RAG metrics
        if rag_used:
            consumption.rag_guided_turns += 1
            consumption.rag_output_tokens_saved += rag_tokens_saved
        
        # Update cost
        consumption.estimated_cost_usd += cost_usd_cents
        if rag_used and rag_tokens_saved > 0:
            # Estimate cost savings (approximate)
            avg_cost_per_output_token = cost_usd_cents / output_tokens if output_tokens > 0 else 0
            consumption.rag_cost_saved_usd += int(rag_tokens_saved * avg_cost_per_output_token)
        
        # Update model usage
        models_used = json.loads(consumption.models_used) if consumption.models_used else {}
        models_used[model] = models_used.get(model, 0) + 1
        consumption.models_used = json.dumps(models_used)
        
        providers_used = json.loads(consumption.providers_used) if consumption.providers_used else {}
        providers_used[provider] = providers_used.get(provider, 0) + 1
        consumption.providers_used = json.dumps(providers_used)
        
        # Update velocity (24h window)
        consumption.turns_last_24h += 1
        
        # Update timestamps
        if consumption.first_usage_at is None:
            consumption.first_usage_at = now
        consumption.last_usage_at = now
        consumption.last_updated_at = now
        
        # Create turn record for audit trail
        turn = ConsumptionTurn(
            user_id=user_id,
            session_id=session_id,
            turn_number=turn_number,
            user_query=user_query,
            session_name=session_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            provider=provider,
            model=model,
            cost_usd_cents=cost_usd_cents,
            status=status,
            rag_used=rag_used,
            rag_tokens_saved=rag_tokens_saved,
            created_at=now
        )
        
        self.db.add(turn)
        self.db.commit()
        
        logger.debug(f"Recorded turn for user {user_id}, session {session_id}, turn {turn_number}: "
                    f"{total_tokens} tokens, status={status}, rag={rag_used}")
    
    def update_session_name(self, user_id: str, session_id: str, session_name: str) -> None:
        """
        Update session_name for all turns in a session.
        Call this when a session name is generated/changed.
        
        Args:
            user_id: User ID
            session_id: Session ID
            session_name: New session name
        """
        # Update all turns for this session
        turns = self.db.query(ConsumptionTurn).filter(
            ConsumptionTurn.user_id == user_id,
            ConsumptionTurn.session_id == session_id
        ).all()
        
        for turn in turns:
            turn.session_name = session_name
        
        if turns:
            self.db.commit()
            logger.debug(f"Updated session_name to '{session_name}' for {len(turns)} turns in session {session_id}")
    
    def increment_session_count(self, user_id: str, session_id: str, is_new_session: bool = True) -> None:
        """
        Increment session counters only if this session hasn't been seen before.
        
        Args:
            user_id: User ID
            session_id: Session ID to check
            is_new_session: True for new session, False for existing (legacy parameter, now verified)
        """
        consumption = self.get_or_create_consumption(user_id)
        now = datetime.now(timezone.utc)
        
        if is_new_session:
            # Check if this session already exists in consumption_turns table
            # Only increment if we've never seen this session_id before
            existing_session = self.db.query(ConsumptionTurn).filter(
                ConsumptionTurn.user_id == user_id,
                ConsumptionTurn.session_id == session_id
            ).first()
            
            if not existing_session:
                # Truly a new session - increment counters
                consumption.total_sessions += 1
                consumption.active_sessions += 1
                consumption.sessions_last_24h += 1
                logger.info(f"New session detected for user {user_id}: {session_id}")
            else:
                logger.debug(f"Session {session_id} already exists for user {user_id}, not incrementing")
        
        consumption.last_updated_at = now
        self.db.commit()
    
    def decrement_active_sessions(self, user_id: str) -> None:
        """
        Decrement active session count (when session closes).
        
        Args:
            user_id: User ID
        """
        consumption = self.get_or_create_consumption(user_id)
        
        if consumption.active_sessions > 0:
            consumption.active_sessions -= 1
            consumption.last_updated_at = datetime.now(timezone.utc)
            self.db.commit()
    
    def increment_champion_cases(self, user_id: str, count: int = 1) -> None:
        """
        Increment champion case counter.
        
        Args:
            user_id: User ID
            count: Number of cases created
        """
        consumption = self.get_or_create_consumption(user_id)
        consumption.champion_cases_created += count
        consumption.last_updated_at = datetime.now(timezone.utc)
        self.db.commit()
    
    def update_collection_subscriptions(self, user_id: str, collection_ids: List[int]) -> None:
        """
        Update user's collection subscriptions.
        
        Args:
            user_id: User ID
            collection_ids: List of collection IDs
        """
        consumption = self.get_or_create_consumption(user_id)
        consumption.collections_subscribed = json.dumps(collection_ids)
        consumption.last_updated_at = datetime.now(timezone.utc)
        self.db.commit()
    
    def rollover_period(self, user_id: str) -> None:
        """
        Archive current period and start new period.
        Should be called at the start of each month.
        
        Args:
            user_id: User ID
        """
        consumption = self.get_or_create_consumption(user_id)
        now = datetime.now(timezone.utc)
        current_period = now.strftime("%Y-%m")
        
        # Skip if already in current period
        if consumption.current_period == current_period:
            return
        
        # Archive previous period
        archive = ConsumptionPeriodsArchive(
            user_id=user_id,
            period=consumption.current_period,
            total_input_tokens=consumption.total_input_tokens,
            total_output_tokens=consumption.total_output_tokens,
            total_tokens=consumption.total_tokens,
            successful_turns=consumption.successful_turns,
            failed_turns=consumption.failed_turns,
            total_turns=consumption.total_turns,
            rag_guided_turns=consumption.rag_guided_turns,
            rag_output_tokens_saved=consumption.rag_output_tokens_saved,
            champion_cases_created=consumption.champion_cases_created,
            estimated_cost_usd=consumption.estimated_cost_usd,
            rag_cost_saved_usd=consumption.rag_cost_saved_usd,
            total_sessions=consumption.total_sessions,
            period_started_at=consumption.period_started_at,
            period_ended_at=now,
            archived_at=now
        )
        
        self.db.add(archive)
        
        # Reset consumption for new period
        consumption.current_period = current_period
        consumption.period_started_at = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        consumption.total_input_tokens = 0
        consumption.total_output_tokens = 0
        consumption.total_tokens = 0
        consumption.successful_turns = 0
        consumption.failed_turns = 0
        consumption.total_turns = 0
        consumption.rag_guided_turns = 0
        consumption.rag_output_tokens_saved = 0
        consumption.champion_cases_created = 0
        consumption.estimated_cost_usd = 0
        consumption.rag_cost_saved_usd = 0
        consumption.total_sessions = 0
        consumption.models_used = None
        consumption.providers_used = None
        consumption.sessions_last_24h = 0
        consumption.turns_last_24h = 0
        consumption.peak_requests_per_hour = 0
        consumption.peak_requests_per_day = 0
        
        self.db.commit()
        
        logger.info(f"Rolled over consumption for user {user_id} from {archive.period} to {current_period}")
    
    def get_consumption_summary(self, user_id: str) -> Dict:
        """
        Get comprehensive consumption summary for user.
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary with all consumption metrics
        """
        consumption = self.get_or_create_consumption(user_id)
        return consumption.to_dict()
    
    def get_users_near_limit(self, threshold_percent: float = 80.0) -> List[Dict]:
        """
        Get users who are near their consumption limits.
        
        Args:
            threshold_percent: Percentage threshold (default 80%)
            
        Returns:
            List of user consumption summaries
        """
        results = []
        
        # Query all users with token limits
        consumptions = self.db.query(UserConsumption).filter(
            (UserConsumption.input_tokens_limit.isnot(None)) |
            (UserConsumption.output_tokens_limit.isnot(None))
        ).all()
        
        for consumption in consumptions:
            near_limit = False
            
            # Check input token threshold
            if consumption.input_tokens_limit:
                usage_percent = (consumption.total_input_tokens / consumption.input_tokens_limit) * 100
                if usage_percent >= threshold_percent:
                    near_limit = True
            
            # Check output token threshold
            if consumption.output_tokens_limit:
                usage_percent = (consumption.total_output_tokens / consumption.output_tokens_limit) * 100
                if usage_percent >= threshold_percent:
                    near_limit = True
            
            if near_limit:
                results.append(consumption.to_dict())
        
        return results
    
    def cleanup_old_turns(self, days_to_keep: int = 90) -> int:
        """
        Clean up old turn records (for storage management).
        
        Args:
            days_to_keep: Number of days to keep (default 90)
            
        Returns:
            Number of records deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        
        deleted = self.db.query(ConsumptionTurn).filter(
            ConsumptionTurn.created_at < cutoff
        ).delete()
        
        self.db.commit()
        
        logger.info(f"Cleaned up {deleted} turn records older than {days_to_keep} days")
        return deleted
    
    def reconcile_session_count(self, user_id: str) -> Dict[str, int]:
        """
        Reconcile session count with actual distinct sessions in consumption_turns.
        This fixes any discrepancies caused by duplicate increments.
        
        Args:
            user_id: User ID to reconcile
            
        Returns:
            Dictionary with old_count, new_count, and difference
        """
        from sqlalchemy import func
        
        consumption = self.get_or_create_consumption(user_id)
        old_count = consumption.total_sessions
        
        # Count actual distinct sessions in consumption_turns
        actual_count = self.db.query(func.count(func.distinct(ConsumptionTurn.session_id))).filter(
            ConsumptionTurn.user_id == user_id
        ).scalar() or 0
        
        if old_count != actual_count:
            logger.info(f"Reconciling session count for user {user_id}: {old_count} -> {actual_count}")
            consumption.total_sessions = actual_count
            self.db.commit()
        
        return {
            'old_count': old_count,
            'new_count': actual_count,
            'difference': actual_count - old_count
        }
