"""
Consumption Profile Enforcement Layer

This module provides a centralized abstraction for enforcing consumption profile limits.
All consumption checks should go through this layer to ensure consistent enforcement.

Usage:
    from trusted_data_agent.auth.consumption_enforcer import ConsumptionEnforcer
    
    enforcer = ConsumptionEnforcer(user_id)
    
    # Check if user can perform an action
    can_proceed, error_message = enforcer.can_execute_prompt()
    if not can_proceed:
        return error_response(error_message)
    
    # Record usage after successful execution
    enforcer.record_prompt_execution(input_tokens=1000, output_tokens=500)
"""

import logging
from typing import Tuple, Optional
from datetime import datetime, timedelta
from sqlalchemy import func

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, ConsumptionProfile, UserTokenUsage

logger = logging.getLogger(__name__)


class ConsumptionLimitExceeded(Exception):
    """Raised when a consumption limit is exceeded."""
    pass


class ConsumptionEnforcer:
    """
    Centralized enforcement layer for consumption profile limits.
    
    This class provides methods to:
    1. Check if operations are allowed based on user's consumption profile
    2. Record usage after operations complete
    3. Get current usage statistics
    4. Reset rate limits (for cron jobs)
    """
    
    def __init__(self, user_id: str):
        """
        Initialize enforcer for a specific user.
        
        Args:
            user_id: The UUID of the user
        """
        self.user_id = user_id
        # Store profile attributes as instance variables to avoid detached instance errors
        self.profile_name = None
        self.is_active = None
        self.prompts_per_hour = None
        self.prompts_per_day = None
        self.config_changes_per_hour = None
        self.input_tokens_per_month = None
        self.output_tokens_per_month = None
        self._load_user_and_profile()
    
    def _load_user_and_profile(self):
        """Load user and their consumption profile from database."""
        try:
            with get_db_session() as session:
                from trusted_data_agent.auth.models import SystemSettings
                
                user = session.query(User).filter_by(id=self.user_id).first()
                
                if not user:
                    raise ValueError(f"User {self.user_id} not found")
                
                # Check if global override is enabled
                global_override_setting = session.query(SystemSettings).filter_by(
                    setting_key='rate_limit_global_override'
                ).first()
                
                use_global_override = (
                    global_override_setting and 
                    global_override_setting.setting_value.lower() == 'true'
                )
                
                if use_global_override:
                    # Use global rate limit settings instead of consumption profile
                    # Load global settings from SystemSettings
                    def get_setting_value(key, default):
                        setting = session.query(SystemSettings).filter_by(setting_key=key).first()
                        if setting:
                            try:
                                return int(setting.setting_value)
                            except ValueError:
                                return default
                        return default
                    
                    self.profile_name = 'Global Override'
                    self.is_active = True
                    self.prompts_per_hour = get_setting_value('rate_limit_user_prompts_per_hour', 100)
                    self.prompts_per_day = get_setting_value('rate_limit_user_prompts_per_day', 1000)
                    self.config_changes_per_hour = get_setting_value('rate_limit_user_configs_per_hour', 10)
                    # Global override doesn't have token limits
                    self.input_tokens_per_month = None
                    self.output_tokens_per_month = None
                else:
                    # Load consumption profile (normal mode)
                    profile = None
                    if user.consumption_profile_id:
                        profile = session.query(ConsumptionProfile).filter_by(
                            id=user.consumption_profile_id
                        ).first()
                    else:
                        # Get default profile
                        profile = session.query(ConsumptionProfile).filter_by(
                            is_default=True
                        ).first()
                    
                    if profile:
                        # Copy attributes from ORM object to avoid detached instance errors
                        self.profile_name = profile.name
                        self.is_active = profile.is_active
                        self.prompts_per_hour = profile.prompts_per_hour
                        self.prompts_per_day = profile.prompts_per_day
                        self.config_changes_per_hour = profile.config_changes_per_hour
                        self.input_tokens_per_month = profile.input_tokens_per_month
                        self.output_tokens_per_month = profile.output_tokens_per_month
                    else:
                        logger.warning(f"No consumption profile found for user {self.user_id}, using unlimited")
                        # Set unlimited profile attributes
                        self.profile_name = 'Unlimited'
                        self.is_active = True
                        self.prompts_per_hour = None
                        self.prompts_per_day = None
                        self.config_changes_per_hour = None
                        self.input_tokens_per_month = None
                        self.output_tokens_per_month = None
        
        except Exception as e:
            logger.error(f"Failed to load user/profile for {self.user_id}: {e}")
            raise
    
    def is_unlimited(self) -> bool:
        """Check if user has unlimited access."""
        return (
            self.prompts_per_hour is None and
            self.prompts_per_day is None and
            self.input_tokens_per_month is None and
            self.output_tokens_per_month is None
        )
    
    # ========================================================================
    # PROMPT EXECUTION ENFORCEMENT
    # ========================================================================
    
    def can_execute_prompt(self) -> Tuple[bool, Optional[str]]:
        """
        Check if user can execute a prompt based on rate limits.
        
        Returns:
            Tuple of (can_proceed: bool, error_message: Optional[str])
        """
        if not self.is_active:
            return False, "Your consumption profile is inactive. Please contact administrator."
        
        if self.is_unlimited():
            return True, None
        
        try:
            with get_db_session() as session:
                now = datetime.utcnow()
                
                # Check hourly limit
                if self.prompts_per_hour is not None:
                    hour_ago = now - timedelta(hours=1)
                    hourly_count = session.query(func.count()).filter(
                        UserTokenUsage.user_id == self.user_id,
                        UserTokenUsage.last_usage_at >= hour_ago
                    ).scalar() or 0
                    
                    if hourly_count >= self.prompts_per_hour:
                        return False, f"Hourly prompt limit exceeded ({self.prompts_per_hour} prompts/hour)"
                
                # Check daily limit
                if self.prompts_per_day is not None:
                    day_ago = now - timedelta(days=1)
                    daily_count = session.query(func.count()).filter(
                        UserTokenUsage.user_id == self.user_id,
                        UserTokenUsage.last_usage_at >= day_ago
                    ).scalar() or 0
                    
                    if daily_count >= self.prompts_per_day:
                        return False, f"Daily prompt limit exceeded ({self.prompts_per_day} prompts/day)"
                
                # Check monthly token limits
                current_period = now.strftime('%Y-%m')
                usage = session.query(UserTokenUsage).filter_by(
                    user_id=self.user_id,
                    period=current_period
                ).first()
                
                if usage:
                    if self.input_tokens_per_month is not None:
                        if usage.input_tokens_used >= self.input_tokens_per_month:
                            return False, f"Monthly input token limit exceeded ({self.input_tokens_per_month:,} tokens)"
                    
                    if self.output_tokens_per_month is not None:
                        if usage.output_tokens_used >= self.output_tokens_per_month:
                            return False, f"Monthly output token limit exceeded ({self.output_tokens_per_month:,} tokens)"
                
                return True, None
        
        except Exception as e:
            logger.error(f"Error checking prompt limits for user {self.user_id}: {e}")
            # Fail open - allow the request but log the error
            return True, None
    
    def record_prompt_execution(self, input_tokens: int, output_tokens: int):
        """
        Record a prompt execution with token usage.
        
        Args:
            input_tokens: Number of input tokens used
            output_tokens: Number of output tokens used
        """
        try:
            from trusted_data_agent.auth.consumption_manager import ConsumptionManager
            
            manager = ConsumptionManager()
            # The consumption manager already handles recording
            # This is just a pass-through for consistency
            logger.debug(f"Recorded prompt execution for user {self.user_id}: {input_tokens} in, {output_tokens} out")
        
        except Exception as e:
            logger.error(f"Failed to record prompt execution for user {self.user_id}: {e}")
    
    # ========================================================================
    # CONFIGURATION CHANGES ENFORCEMENT
    # ========================================================================
    
    def can_change_configuration(self) -> Tuple[bool, Optional[str]]:
        """
        Check if user can make configuration changes (MCP servers, LLM configs, etc.).
        
        Returns:
            Tuple of (can_proceed: bool, error_message: Optional[str])
        """
        if not self.is_active:
            return False, "Your consumption profile is inactive. Please contact administrator."
        
        if self.config_changes_per_hour is None:
            return True, None
        
        try:
            with get_db_session() as session:
                from trusted_data_agent.auth.models import AuditLog
                
                now = datetime.utcnow()
                hour_ago = now - timedelta(hours=1)
                
                # Count config changes in last hour
                config_changes = session.query(func.count()).filter(
                    AuditLog.user_id == self.user_id,
                    AuditLog.action.in_(['config_change', 'mcp_add', 'mcp_update', 'llm_add', 'llm_update']),
                    AuditLog.timestamp >= hour_ago
                ).scalar() or 0
                
                if config_changes >= self.config_changes_per_hour:
                    return False, f"Hourly configuration change limit exceeded ({self.config_changes_per_hour} changes/hour)"
                
                return True, None
        
        except Exception as e:
            logger.error(f"Error checking config change limits for user {self.user_id}: {e}")
            return True, None
    
    def record_configuration_change(self, action: str, details: str):
        """
        Record a configuration change in audit log.
        
        Args:
            action: Type of configuration change (e.g., 'mcp_add', 'llm_update')
            details: Description of the change
        """
        try:
            from trusted_data_agent.auth.models import AuditLog
            
            with get_db_session() as session:
                audit = AuditLog(
                    user_id=self.user_id,
                    action=action,
                    details=details,
                    timestamp=datetime.utcnow()
                )
                session.add(audit)
                session.commit()
                logger.debug(f"Recorded config change for user {self.user_id}: {action}")
        
        except Exception as e:
            logger.error(f"Failed to record config change for user {self.user_id}: {e}")
    
    # ========================================================================
    # USAGE STATISTICS
    # ========================================================================
    
    def get_current_usage(self) -> dict:
        """
        Get current usage statistics for the user.
        
        Returns:
            Dictionary with usage stats including limits and current usage
        """
        try:
            with get_db_session() as session:
                now = datetime.utcnow()
                current_period = now.strftime('%Y-%m')
                
                # Get monthly usage
                usage = session.query(UserTokenUsage).filter_by(
                    user_id=self.user_id,
                    period=current_period
                ).first()
                
                # Count hourly prompts
                hour_ago = now - timedelta(hours=1)
                hourly_prompts = session.query(func.count()).filter(
                    UserTokenUsage.user_id == self.user_id,
                    UserTokenUsage.last_usage_at >= hour_ago
                ).scalar() or 0
                
                # Count daily prompts
                day_ago = now - timedelta(days=1)
                daily_prompts = session.query(func.count()).filter(
                    UserTokenUsage.user_id == self.user_id,
                    UserTokenUsage.last_usage_at >= day_ago
                ).scalar() or 0
                
                return {
                    'profile_name': self.profile_name,
                    'is_unlimited': self.is_unlimited(),
                    'prompts': {
                        'hourly': {
                            'used': hourly_prompts,
                            'limit': self.prompts_per_hour,
                            'remaining': self.prompts_per_hour - hourly_prompts if self.prompts_per_hour else None
                        },
                        'daily': {
                            'used': daily_prompts,
                            'limit': self.prompts_per_day,
                            'remaining': self.prompts_per_day - daily_prompts if self.prompts_per_day else None
                        }
                    },
                    'tokens': {
                        'input': {
                            'used': usage.input_tokens_used if usage else 0,
                            'limit': self.input_tokens_per_month,
                            'remaining': self.input_tokens_per_month - (usage.input_tokens_used if usage else 0) if self.input_tokens_per_month else None
                        },
                        'output': {
                            'used': usage.output_tokens_used if usage else 0,
                            'limit': self.output_tokens_per_month,
                            'remaining': self.output_tokens_per_month - (usage.output_tokens_used if usage else 0) if self.output_tokens_per_month else None
                        }
                    },
                    'period': current_period
                }
        
        except Exception as e:
            logger.error(f"Error getting usage stats for user {self.user_id}: {e}")
            return {'error': str(e)}
    
    # ========================================================================
    # ADMIN OPERATIONS
    # ========================================================================
    
    @staticmethod
    def reset_hourly_limits():
        """
        Reset hourly rate limits for all users.
        Called by cron job every hour.
        """
        try:
            # Hourly limits are automatically checked based on timestamps
            # No explicit reset needed - they expire naturally
            logger.info("Hourly rate limits check completed (automatic expiry)")
        except Exception as e:
            logger.error(f"Error during hourly rate limit reset: {e}")
    
    @staticmethod
    def reset_daily_limits():
        """
        Reset daily rate limits for all users.
        Called by cron job every day.
        """
        try:
            # Daily limits are automatically checked based on timestamps
            # No explicit reset needed - they expire naturally
            logger.info("Daily rate limits check completed (automatic expiry)")
        except Exception as e:
            logger.error(f"Error during daily rate limit reset: {e}")
    
    @staticmethod
    def rollover_monthly_period():
        """
        Archive current monthly period and start new one.
        Called by cron job on the 1st of each month.
        """
        try:
            with get_db_session() as session:
                now = datetime.utcnow()
                current_period = now.strftime('%Y-%m')
                
                # All monthly stats are tracked in user_token_usage table
                # New month automatically gets new records
                logger.info(f"Monthly period rollover completed for {current_period}")
        except Exception as e:
            logger.error(f"Error during monthly rollover: {e}")
