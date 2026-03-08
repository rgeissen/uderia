"""
Rate limiting implementation using token bucket algorithm.

Provides per-user and per-IP rate limiting to prevent abuse.
Uses in-memory storage with periodic cleanup (can be extended to use Redis in production).
"""

import os
import time
import logging
from typing import Optional, Dict, Tuple
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps

from quart import request, jsonify

logger = logging.getLogger("quart.app")

# Cache for rate limit configuration (refreshed periodically)
_config_cache = {}
_config_cache_time = 0
CONFIG_CACHE_TTL = 60  # Cache config for 60 seconds


def _get_rate_limit_config():
    """
    Get rate limit configuration from database with caching.
    Falls back to environment variables if database is unavailable.
    """
    global _config_cache, _config_cache_time
    
    current_time = time.time()
    
    # Return cached config if still valid
    if _config_cache and (current_time - _config_cache_time) < CONFIG_CACHE_TTL:
        return _config_cache
    
    # Try to load from database
    try:
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import SystemSettings
        
        with get_db_session() as session:
            settings = session.query(SystemSettings).filter(
                SystemSettings.setting_key.like('rate_limit_%')
            ).all()
            
            config = {}
            for setting in settings:
                if setting.setting_key == 'rate_limit_enabled':
                    config['enabled'] = setting.setting_value.lower() == 'true'
                elif setting.setting_key == 'rate_limit_global_override':
                    config['global_override'] = setting.setting_value.lower() == 'true'
                elif setting.setting_key == 'rate_limit_user_prompts_per_hour':
                    config['user_prompts_per_hour'] = int(setting.setting_value)
                elif setting.setting_key == 'rate_limit_user_prompts_per_day':
                    config['user_prompts_per_day'] = int(setting.setting_value)
                elif setting.setting_key == 'rate_limit_user_configs_per_hour':
                    config['user_configs_per_hour'] = int(setting.setting_value)
                elif setting.setting_key == 'rate_limit_ip_login_per_minute':
                    config['ip_login_per_minute'] = int(setting.setting_value)
                elif setting.setting_key == 'rate_limit_ip_register_per_hour':
                    config['ip_register_per_hour'] = int(setting.setting_value)
                elif setting.setting_key == 'rate_limit_ip_api_per_minute':
                    config['ip_api_per_minute'] = int(setting.setting_value)
            
            # Update cache
            _config_cache = config
            _config_cache_time = current_time
            
            return config
    
    except Exception as e:
        logger.warning(f"Failed to load rate limit config from database, using environment variables: {e}")
        # Fall back to environment variables
        config = {
            'enabled': os.environ.get('TDA_RATE_LIMIT_ENABLED', 'true').lower() == 'true',
            'global_override': os.environ.get('TDA_RATE_LIMIT_GLOBAL_OVERRIDE', 'false').lower() == 'true',
            'user_prompts_per_hour': int(os.environ.get('TDA_USER_PROMPTS_PER_HOUR', '100')),
            'user_prompts_per_day': int(os.environ.get('TDA_USER_PROMPTS_PER_DAY', '1000')),
            'user_configs_per_hour': int(os.environ.get('TDA_USER_CONFIGS_PER_HOUR', '10')),
            'ip_login_per_minute': int(os.environ.get('TDA_IP_LOGIN_PER_MINUTE', '5')),
            'ip_register_per_hour': int(os.environ.get('TDA_IP_REGISTER_PER_HOUR', '3')),
            'ip_api_per_minute': int(os.environ.get('TDA_IP_API_PER_MINUTE', '60'))
        }
        return config


# Get current configuration
def _is_rate_limit_enabled():
    """Check if rate limiting is enabled."""
    config = _get_rate_limit_config()
    return config.get('enabled', False)

# In-memory storage for rate limits
# Structure: {identifier: {bucket_key: (tokens, last_update_time)}}
_rate_limits: Dict[str, Dict[str, Tuple[float, float]]] = defaultdict(dict)
_last_cleanup = time.time()
CLEANUP_INTERVAL = 3600  # Clean up every hour


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")


def _get_client_ip() -> str:
    """
    Get client IP address from request, considering proxies.
    
    Returns:
        IP address string
    """
    # Check X-Forwarded-For header (from proxy)
    if 'X-Forwarded-For' in request.headers:
        # Take first IP in chain
        return request.headers['X-Forwarded-For'].split(',')[0].strip()
    
    # Check X-Real-IP header
    if 'X-Real-IP' in request.headers:
        return request.headers['X-Real-IP']
    
    # Fall back to remote_addr
    return request.remote_addr or 'unknown'


def _cleanup_old_entries():
    """Remove stale entries from rate limit storage."""
    global _last_cleanup, _rate_limits
    
    current_time = time.time()
    
    # Only cleanup every CLEANUP_INTERVAL seconds
    if current_time - _last_cleanup < CLEANUP_INTERVAL:
        return
    
    # Remove entries older than 24 hours
    cutoff = current_time - 86400
    
    identifiers_to_remove = []
    for identifier, buckets in _rate_limits.items():
        # Remove old buckets
        old_buckets = [key for key, (tokens, last_update) in buckets.items() if last_update < cutoff]
        for key in old_buckets:
            del buckets[key]
        
        # If no buckets left, mark identifier for removal
        if not buckets:
            identifiers_to_remove.append(identifier)
    
    # Remove empty identifiers
    for identifier in identifiers_to_remove:
        del _rate_limits[identifier]
    
    _last_cleanup = current_time
    
    if identifiers_to_remove:
        logger.debug(f"Rate limiter cleanup: removed {len(identifiers_to_remove)} stale entries")


def check_rate_limit(
    identifier: str,
    limit: int,
    window: int,
    bucket_key: Optional[str] = None
) -> Tuple[bool, int]:
    """
    Check if rate limit is exceeded using token bucket algorithm.
    
    Args:
        identifier: Unique identifier (user_id, IP address, etc.)
        limit: Maximum number of requests allowed
        window: Time window in seconds
        bucket_key: Optional key to track multiple limits per identifier
        
    Returns:
        Tuple of (is_allowed, retry_after_seconds)
    """
    if not _is_rate_limit_enabled():
        return True, 0
    
    # Periodic cleanup
    _cleanup_old_entries()
    
    current_time = time.time()
    bucket_key = bucket_key or f"{limit}_{window}"
    
    # Get current bucket state
    buckets = _rate_limits[identifier]
    tokens, last_update = buckets.get(bucket_key, (float(limit), current_time))
    
    # Calculate token refill based on time passed
    time_passed = current_time - last_update
    refill_rate = limit / window  # tokens per second
    tokens = min(limit, tokens + time_passed * refill_rate)
    
    # Check if request can be allowed
    if tokens >= 1.0:
        # Allow request and consume token
        tokens -= 1.0
        buckets[bucket_key] = (tokens, current_time)
        return True, 0
    else:
        # Rate limit exceeded
        # Calculate retry after time
        tokens_needed = 1.0 - tokens
        retry_after = int(tokens_needed / refill_rate) + 1
        
        # Update last_update time even on rejection
        buckets[bucket_key] = (tokens, current_time)
        
        logger.warning(f"Rate limit exceeded for {identifier} (bucket: {bucket_key})")
        return False, retry_after


def rate_limit(limit: int, window: int, bucket_key: Optional[str] = None):
    """
    Decorator for rate limiting endpoints.
    
    Args:
        limit: Maximum number of requests allowed
        window: Time window in seconds
        bucket_key: Optional key to differentiate multiple limits
        
    Usage:
        @rate_limit(limit=5, window=60)  # 5 requests per minute
        async def my_endpoint():
            ...
    """
    def decorator(f):
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            if not _is_rate_limit_enabled():
                return await f(*args, **kwargs)
            
            # Try to get user_id first (authenticated request)
            identifier = None
            try:
                from trusted_data_agent.auth.middleware import get_current_user
                user = get_current_user()
                if user:
                    identifier = f"user:{user.id}"
            except:
                pass
            
            # Fall back to IP address
            if not identifier:
                identifier = f"ip:{_get_client_ip()}"
            
            # Check rate limit
            allowed, retry_after = check_rate_limit(identifier, limit, window, bucket_key)
            
            if not allowed:
                return jsonify({
                    'status': 'error',
                    'message': 'Rate limit exceeded',
                    'retry_after': retry_after
                }), 429  # Too Many Requests
            
            return await f(*args, **kwargs)
        
        return decorated_function
    return decorator


def check_user_prompt_quota(user_id: str) -> Tuple[bool, str]:
    """
    Check if user has exceeded prompt execution quotas.
    Uses consumption profile if assigned, otherwise falls back to system defaults.
    
    Args:
        user_id: User's unique identifier
        
    Returns:
        Tuple of (is_allowed, error_message)
    """
    if not _is_rate_limit_enabled():
        return True, ""
    
    config = _get_rate_limit_config()
    
    # Check if global override is enabled (emergency mode)
    if config.get('global_override', False):
        user_prompts_per_hour = config.get('user_prompts_per_hour', 100)
        user_prompts_per_day = config.get('user_prompts_per_day', 1000)
    else:
        # Try to get limits from user's consumption profile
        try:
            from trusted_data_agent.auth.token_quota import get_user_consumption_profile
            profile = get_user_consumption_profile(user_id)
            
            if profile:
                user_prompts_per_hour = profile.prompts_per_hour
                user_prompts_per_day = profile.prompts_per_day
            else:
                # Fall back to system defaults
                user_prompts_per_hour = config.get('user_prompts_per_hour', 100)
                user_prompts_per_day = config.get('user_prompts_per_day', 1000)
        except Exception as e:
            logger.warning(f"Error fetching consumption profile, using system defaults: {e}")
            user_prompts_per_hour = config.get('user_prompts_per_hour', 100)
            user_prompts_per_day = config.get('user_prompts_per_day', 1000)
    
    # Check hourly limit
    allowed, retry_after = check_rate_limit(
        f"user:{user_id}",
        user_prompts_per_hour,
        3600,
        "prompts_hourly"
    )
    
    if not allowed:
        return False, f"Hourly prompt limit exceeded ({user_prompts_per_hour}/hour). Retry in {retry_after} seconds."
    
    # Check daily limit
    allowed, retry_after = check_rate_limit(
        f"user:{user_id}",
        user_prompts_per_day,
        86400,
        "prompts_daily"
    )
    
    if not allowed:
        hours = retry_after // 3600
        return False, f"Daily prompt limit exceeded ({user_prompts_per_day}/day). Retry in {hours} hours."
    
    return True, ""


def check_user_config_quota(user_id: str) -> Tuple[bool, str]:
    """
    Check if user has exceeded configuration change quotas.
    Uses consumption profile if assigned, otherwise falls back to system defaults.
    
    Args:
        user_id: User's unique identifier
        
    Returns:
        Tuple of (is_allowed, error_message)
    """
    if not _is_rate_limit_enabled():
        return True, ""
    
    config = _get_rate_limit_config()
    
    # Check if global override is enabled (emergency mode)
    if config.get('global_override', False):
        user_configs_per_hour = config.get('user_configs_per_hour', 10)
    else:
        # Try to get limits from user's consumption profile
        try:
            from trusted_data_agent.auth.token_quota import get_user_consumption_profile
            profile = get_user_consumption_profile(user_id)
            
            if profile:
                user_configs_per_hour = profile.config_changes_per_hour
            else:
                # Fall back to system defaults
                user_configs_per_hour = config.get('user_configs_per_hour', 10)
        except Exception as e:
            logger.warning(f"Error fetching consumption profile, using system defaults: {e}")
            user_configs_per_hour = config.get('user_configs_per_hour', 10)
    
    allowed, retry_after = check_rate_limit(
        f"user:{user_id}",
        user_configs_per_hour,
        3600,
        "configs_hourly"
    )
    
    if not allowed:
        return False, f"Configuration limit exceeded ({user_configs_per_hour}/hour). Retry in {retry_after} seconds."
    
    return True, ""


def check_ip_login_limit(ip_address: Optional[str] = None) -> Tuple[bool, int]:
    """
    Check if IP has exceeded login attempt limits.
    
    Args:
        ip_address: Optional IP address (defaults to request IP)
        
    Returns:
        Tuple of (is_allowed, retry_after_seconds)
    """
    if not _is_rate_limit_enabled():
        return True, 0
    
    config = _get_rate_limit_config()
    ip_login_per_minute = config.get('ip_login_per_minute', 5)
    
    ip = ip_address or _get_client_ip()
    
    return check_rate_limit(
        f"ip:{ip}",
        ip_login_per_minute,
        60,
        "login"
    )


def check_ip_register_limit(ip_address: Optional[str] = None) -> Tuple[bool, int]:
    """
    Check if IP has exceeded registration limits.
    
    Args:
        ip_address: Optional IP address (defaults to request IP)
        
    Returns:
        Tuple of (is_allowed, retry_after_seconds)
    """
    if not _is_rate_limit_enabled():
        return True, 0
    
    config = _get_rate_limit_config()
    ip_register_per_hour = config.get('ip_register_per_hour', 3)
    
    ip = ip_address or _get_client_ip()
    
    return check_rate_limit(
        f"ip:{ip}",
        ip_register_per_hour,
        3600,
        "register"
    )


def reset_rate_limits(identifier: str):
    """
    Reset all rate limits for an identifier (e.g., on successful login).
    
    Args:
        identifier: User ID or IP address
    """
    if identifier in _rate_limits:
        del _rate_limits[identifier]
        logger.debug(f"Reset rate limits for {identifier}")


def get_rate_limit_status(identifier: str) -> Dict[str, Dict[str, any]]:
    """
    Get current rate limit status for an identifier.
    
    Args:
        identifier: User ID or IP address
        
    Returns:
        Dictionary of bucket statuses
    """
    if identifier not in _rate_limits:
        return {}
    
    status = {}
    buckets = _rate_limits[identifier]
    
    for bucket_key, (tokens, last_update) in buckets.items():
        status[bucket_key] = {
            'tokens_remaining': int(tokens),
            'last_update': datetime.fromtimestamp(last_update, tz=timezone.utc).isoformat()
        }
    
    return status
