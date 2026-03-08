"""
Token quota management and enforcement.

Tracks and enforces token consumption limits based on user consumption profiles.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict
from sqlalchemy import func

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, ConsumptionProfile, UserTokenUsage

logger = logging.getLogger("quart.app")


def get_current_period() -> str:
    """Get current period in YYYY-MM format."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_user_consumption_profile(user_id: str) -> Optional[Dict]:
    """
    Get user's consumption profile as a dictionary.
    
    Args:
        user_id: User's unique identifier
        
    Returns:
        Profile dictionary or None
    """
    try:
        with get_db_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return None
            
            # If user has a profile assigned, use it
            if user.consumption_profile_id:
                profile = session.query(ConsumptionProfile).filter_by(
                    id=user.consumption_profile_id,
                    is_active=True
                ).first()
                if profile:
                    # Return as dict to avoid detached instance issues
                    return {
                        'id': profile.id,
                        'name': profile.name,
                        'prompts_per_hour': profile.prompts_per_hour,
                        'prompts_per_day': profile.prompts_per_day,
                        'config_changes_per_hour': profile.config_changes_per_hour,
                        'input_tokens_per_month': profile.input_tokens_per_month,
                        'output_tokens_per_month': profile.output_tokens_per_month
                    }
            
            # Otherwise, get the default profile
            default_profile = session.query(ConsumptionProfile).filter_by(
                is_default=True,
                is_active=True
            ).first()
            
            if default_profile:
                return {
                    'id': default_profile.id,
                    'name': default_profile.name,
                    'prompts_per_hour': default_profile.prompts_per_hour,
                    'prompts_per_day': default_profile.prompts_per_day,
                    'config_changes_per_hour': default_profile.config_changes_per_hour,
                    'input_tokens_per_month': default_profile.input_tokens_per_month,
                    'output_tokens_per_month': default_profile.output_tokens_per_month
                }
            
            return None
    except Exception as e:
        logger.error(f"Error fetching consumption profile for user {user_id}: {e}", exc_info=True)
        return None


def get_user_token_usage(user_id: str, period: Optional[str] = None) -> UserTokenUsage:
    """
    Get or create token usage record for user in given period.
    
    Args:
        user_id: User's unique identifier
        period: Period in YYYY-MM format (defaults to current period)
        
    Returns:
        UserTokenUsage record
    """
    if not period:
        period = get_current_period()
    
    try:
        with get_db_session() as session:
            usage = session.query(UserTokenUsage).filter_by(
                user_id=user_id,
                period=period
            ).first()
            
            if not usage:
                usage = UserTokenUsage(
                    user_id=user_id,
                    period=period,
                    input_tokens_used=0,
                    output_tokens_used=0,
                    total_tokens_used=0
                )
                session.add(usage)
                session.commit()
                session.refresh(usage)
            
            return usage
    except Exception as e:
        logger.error(f"Error fetching token usage for user {user_id}: {e}", exc_info=True)
        # Return empty usage record on error
        return UserTokenUsage(
            user_id=user_id,
            period=period,
            input_tokens_used=0,
            output_tokens_used=0,
            total_tokens_used=0
        )


def check_token_quota(
    user_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0
) -> Tuple[bool, str, Dict[str, int]]:
    """
    Check if user has sufficient token quota for the request.
    
    Args:
        user_id: User's unique identifier
        input_tokens: Number of input tokens for this request
        output_tokens: Number of output tokens for this request
        
    Returns:
        Tuple of (is_allowed, error_message, quota_info)
        quota_info contains: {
            'input_limit': int or None,
            'output_limit': int or None,
            'input_used': int,
            'output_used': int,
            'input_remaining': int or None,
            'output_remaining': int or None
        }
    """
    try:
        # Get user's consumption profile
        profile = get_user_consumption_profile(user_id)
        
        # If no profile or unlimited quotas, allow
        if not profile or (
            profile['input_tokens_per_month'] is None and 
            profile['output_tokens_per_month'] is None
        ):
            return True, "", {
                'input_limit': None,
                'output_limit': None,
                'input_used': 0,
                'output_used': 0,
                'input_remaining': None,
                'output_remaining': None
            }
        
        # Get current usage
        period = get_current_period()
        usage = get_user_token_usage(user_id, period)
        
        quota_info = {
            'input_limit': profile['input_tokens_per_month'],
            'output_limit': profile['output_tokens_per_month'],
            'input_used': usage.input_tokens_used,
            'output_used': usage.output_tokens_used,
            'input_remaining': None,
            'output_remaining': None
        }
        
        # Check input token quota
        if profile['input_tokens_per_month'] is not None:
            input_remaining = profile['input_tokens_per_month'] - usage.input_tokens_used
            quota_info['input_remaining'] = input_remaining
            
            if usage.input_tokens_used + input_tokens > profile['input_tokens_per_month']:
                return False, (
                    f"Input token quota exceeded. "
                    f"Limit: {profile['input_tokens_per_month']:,}/month, "
                    f"Used: {usage.input_tokens_used:,}, "
                    f"Remaining: {input_remaining:,}"
                ), quota_info
        
        # Check output token quota
        if profile['output_tokens_per_month'] is not None:
            output_remaining = profile['output_tokens_per_month'] - usage.output_tokens_used
            quota_info['output_remaining'] = output_remaining
            
            if usage.output_tokens_used + output_tokens > profile['output_tokens_per_month']:
                return False, (
                    f"Output token quota exceeded. "
                    f"Limit: {profile['output_tokens_per_month']:,}/month, "
                    f"Used: {usage.output_tokens_used:,}, "
                    f"Remaining: {output_remaining:,}"
                ), quota_info
        
        return True, "", quota_info
        
    except Exception as e:
        logger.error(f"Error checking token quota for user {user_id}: {e}", exc_info=True)
        # On error, allow the request (fail open)
        return True, "", {}


def record_token_usage(
    user_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0
) -> bool:
    """
    Record token usage for a user.
    
    Args:
        user_id: User's unique identifier
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens used
        
    Returns:
        True if recorded successfully, False otherwise
    """
    try:
        period = get_current_period()
        
        with get_db_session() as session:
            usage = session.query(UserTokenUsage).filter_by(
                user_id=user_id,
                period=period
            ).first()
            
            if not usage:
                usage = UserTokenUsage(
                    user_id=user_id,
                    period=period,
                    input_tokens_used=input_tokens,
                    output_tokens_used=output_tokens,
                    total_tokens_used=input_tokens + output_tokens
                )
                session.add(usage)
            else:
                usage.input_tokens_used += input_tokens
                usage.output_tokens_used += output_tokens
                usage.total_tokens_used += (input_tokens + output_tokens)
                usage.last_usage_at = datetime.now(timezone.utc)
            
            session.commit()
            
            logger.debug(
                f"Recorded token usage for user {user_id[:8]}: "
                f"input={input_tokens}, output={output_tokens}"
            )
            return True
            
    except Exception as e:
        logger.error(f"Error recording token usage for user {user_id}: {e}", exc_info=True)
        return False


def get_user_quota_status(user_id: str) -> Dict:
    """
    Get comprehensive quota status for a user.
    
    Args:
        user_id: User's unique identifier
        
    Returns:
        Dictionary with quota limits, usage, and remaining tokens
    """
    try:
        profile = get_user_consumption_profile(user_id)
        period = get_current_period()
        
        # Get usage and convert to dict within session context
        with get_db_session() as session:
            usage_obj = session.query(UserTokenUsage).filter_by(
                user_id=user_id,
                period=period
            ).first()
            
            if usage_obj:
                usage = {
                    'input_tokens_used': usage_obj.input_tokens_used,
                    'output_tokens_used': usage_obj.output_tokens_used,
                    'total_tokens_used': usage_obj.total_tokens_used
                }
            else:
                usage = {
                    'input_tokens_used': 0,
                    'output_tokens_used': 0,
                    'total_tokens_used': 0
                }
        
        if not profile:
            return {
                'has_quota': False,
                'period': period,
                'profile_name': None,
                'input_tokens': {
                    'limit': None,
                    'used': usage['input_tokens_used'],
                    'remaining': None,
                    'percentage_used': 0
                },
                'output_tokens': {
                    'limit': None,
                    'used': usage['output_tokens_used'],
                    'remaining': None,
                    'percentage_used': 0
                },
                'rate_limits': {
                    'prompts_per_hour': None,
                    'prompts_per_day': None,
                    'config_changes_per_hour': None
                }
            }
        
        input_remaining = None
        input_percentage = 0
        if profile['input_tokens_per_month'] is not None:
            input_remaining = max(0, profile['input_tokens_per_month'] - usage['input_tokens_used'])
            input_percentage = min(100, (usage['input_tokens_used'] / profile['input_tokens_per_month']) * 100)
        
        output_remaining = None
        output_percentage = 0
        if profile['output_tokens_per_month'] is not None:
            output_remaining = max(0, profile['output_tokens_per_month'] - usage['output_tokens_used'])
            output_percentage = min(100, (usage['output_tokens_used'] / profile['output_tokens_per_month']) * 100)
        
        return {
            'has_quota': True,
            'period': period,
            'profile_name': profile['name'],
            'profile_id': profile['id'],
            'input_tokens': {
                'limit': profile['input_tokens_per_month'],
                'used': usage['input_tokens_used'],
                'remaining': input_remaining,
                'percentage_used': round(input_percentage, 1)
            },
            'output_tokens': {
                'limit': profile['output_tokens_per_month'],
                'used': usage['output_tokens_used'],
                'remaining': output_remaining,
                'percentage_used': round(output_percentage, 1)
            },
            'rate_limits': {
                'prompts_per_hour': profile['prompts_per_hour'],
                'prompts_per_day': profile['prompts_per_day'],
                'config_changes_per_hour': profile['config_changes_per_hour']
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting quota status for user {user_id}: {e}", exc_info=True)
        return {
            'error': str(e),
            'has_quota': False
        }
