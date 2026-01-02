"""
OAuth rate limiting service.

Implements rate limiting for OAuth endpoints to prevent abuse.
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from collections import defaultdict

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import AuditLog

logger = logging.getLogger("quart.app")


class OAuthRateLimiter:
    """Rate limiter for OAuth operations."""
    
    # In-memory rate limit tracking (provider -> IP -> timestamps)
    # In production, use Redis for distributed rate limiting
    _oauth_attempts = defaultdict(lambda: defaultdict(list))
    
    # Rate limiting configuration
    OAUTH_LOGIN_ATTEMPTS_PER_HOUR = 20
    OAUTH_LINK_ATTEMPTS_PER_HOUR = 10
    OAUTH_CALLBACK_ATTEMPTS_PER_HOUR = 50
    
    CLEANUP_INTERVAL = 3600  # Clean old entries every hour
    _last_cleanup = time.time()
    
    @staticmethod
    def check_oauth_login_limit(ip_address: str, provider: str) -> Tuple[bool, int]:
        """
        Check if OAuth login attempts exceed limit.
        
        Args:
            ip_address: Client IP address
            provider: OAuth provider name
            
        Returns:
            Tuple of (allowed: bool, attempts: int)
        """
        return OAuthRateLimiter._check_limit(
            f'oauth_login:{provider}',
            ip_address,
            OAuthRateLimiter.OAUTH_LOGIN_ATTEMPTS_PER_HOUR
        )
    
    @staticmethod
    def check_oauth_link_limit(user_id: str, provider: str) -> Tuple[bool, int]:
        """
        Check if OAuth account link attempts exceed limit.
        
        Args:
            user_id: User ID
            provider: OAuth provider name
            
        Returns:
            Tuple of (allowed: bool, attempts: int)
        """
        return OAuthRateLimiter._check_limit(
            f'oauth_link:{provider}',
            user_id,
            OAuthRateLimiter.OAUTH_LINK_ATTEMPTS_PER_HOUR
        )
    
    @staticmethod
    def check_oauth_callback_limit(ip_address: str, provider: str) -> Tuple[bool, int]:
        """
        Check if OAuth callback attempts exceed limit.
        
        Args:
            ip_address: Client IP address
            provider: OAuth provider name
            
        Returns:
            Tuple of (allowed: bool, attempts: int)
        """
        return OAuthRateLimiter._check_limit(
            f'oauth_callback:{provider}',
            ip_address,
            OAuthRateLimiter.OAUTH_CALLBACK_ATTEMPTS_PER_HOUR
        )
    
    @staticmethod
    def record_oauth_attempt(
        operation: str,
        provider: str,
        identifier: str,  # IP or user ID
        success: bool = True
    ):
        """
        Record an OAuth operation attempt for rate limiting and auditing.
        
        Args:
            operation: Type of operation ('login', 'link', 'callback', etc.)
            provider: OAuth provider name
            identifier: IP address or user ID
            success: Whether operation was successful
        """
        key = f'oauth_{operation}:{provider}'
        OAuthRateLimiter._oauth_attempts[key][identifier].append({
            'timestamp': time.time(),
            'success': success
        })
        
        # Periodic cleanup of old entries
        current_time = time.time()
        if current_time - OAuthRateLimiter._last_cleanup > OAuthRateLimiter.CLEANUP_INTERVAL:
            OAuthRateLimiter._cleanup_old_entries()
            OAuthRateLimiter._last_cleanup = current_time
    
    @staticmethod
    def _check_limit(key: str, identifier: str, limit: int) -> Tuple[bool, int]:
        """
        Check if operation is within rate limit.
        
        Args:
            key: Rate limit key (e.g., 'oauth_login:google')
            identifier: IP address or user ID
            limit: Maximum attempts allowed per hour
            
        Returns:
            Tuple of (allowed: bool, attempts: int)
        """
        current_time = time.time()
        one_hour_ago = current_time - 3600
        
        # Get attempts in the last hour
        attempts = OAuthRateLimiter._oauth_attempts[key][identifier]
        recent_attempts = [a for a in attempts if a['timestamp'] > one_hour_ago]
        
        # Update the list
        OAuthRateLimiter._oauth_attempts[key][identifier] = recent_attempts
        
        attempt_count = len(recent_attempts)
        allowed = attempt_count < limit
        
        if not allowed:
            logger.warning(f"Rate limit exceeded for {key}:{identifier} ({attempt_count}/{limit} attempts)")
        
        return allowed, attempt_count
    
    @staticmethod
    def _cleanup_old_entries():
        """Clean up old rate limit entries."""
        current_time = time.time()
        one_hour_ago = current_time - 3600
        
        cleaned = 0
        for key in list(OAuthRateLimiter._oauth_attempts.keys()):
            for identifier in list(OAuthRateLimiter._oauth_attempts[key].keys()):
                # Remove old entries
                original_count = len(OAuthRateLimiter._oauth_attempts[key][identifier])
                OAuthRateLimiter._oauth_attempts[key][identifier] = [
                    a for a in OAuthRateLimiter._oauth_attempts[key][identifier]
                    if a['timestamp'] > one_hour_ago
                ]
                cleaned += original_count - len(OAuthRateLimiter._oauth_attempts[key][identifier])
                
                # Remove empty identifiers
                if not OAuthRateLimiter._oauth_attempts[key][identifier]:
                    del OAuthRateLimiter._oauth_attempts[key][identifier]
            
            # Remove empty keys
            if not OAuthRateLimiter._oauth_attempts[key]:
                del OAuthRateLimiter._oauth_attempts[key]
        
        if cleaned > 0:
            logger.debug(f"Cleaned up {cleaned} old rate limit entries")


class OAuthAbuseDetector:
    """Detects and logs potential abuse patterns in OAuth usage."""
    
    @staticmethod
    def detect_brute_force(ip_address: str, provider: str, failed_attempts: int = 5) -> bool:
        """
        Detect brute force attacks on OAuth login.
        
        Args:
            ip_address: Client IP address
            provider: OAuth provider name
            failed_attempts: Threshold for failed attempts
            
        Returns:
            True if brute force detected, False otherwise
        """
        key = f'oauth_login:{provider}'
        attempts = OAuthRateLimiter._oauth_attempts[key].get(ip_address, [])
        
        current_time = time.time()
        five_minutes_ago = current_time - (5 * 60)
        
        # Count failed attempts in last 5 minutes
        failed = sum(1 for a in attempts if a['timestamp'] > five_minutes_ago and not a['success'])
        
        if failed >= failed_attempts:
            logger.warning(f"Potential brute force detected: {ip_address} on {provider} ({failed} failed attempts)")
            OAuthAbuseDetector._log_abuse_attempt(
                ip_address=ip_address,
                provider=provider,
                abuse_type='brute_force',
                details=f"{failed} failed login attempts in 5 minutes"
            )
            return True
        
        return False
    
    @staticmethod
    def detect_account_enumeration(ip_address: str, provider: str, unique_accounts: int = 10) -> bool:
        """
        Detect account enumeration attacks.
        
        Args:
            ip_address: Client IP address
            provider: OAuth provider name
            unique_accounts: Threshold for unique account attempts
            
        Returns:
            True if enumeration detected, False otherwise
        """
        # This would require tracking user accounts per IP
        # Implementation depends on your audit logging structure
        return False
    
    @staticmethod
    def detect_rapid_account_linking(user_id: str, provider_count: int = 5) -> bool:
        """
        Detect suspicious rapid account linking.
        
        Args:
            user_id: User ID
            provider_count: Threshold for rapid linking
            
        Returns:
            True if rapid linking detected, False otherwise
        """
        try:
            with get_db_session() as session:
                # Count OAuth accounts linked in last hour
                one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
                
                count = session.query(OAuthAccount).filter(
                    OAuthAccount.user_id == user_id,
                    OAuthAccount.created_at > one_hour_ago
                ).count()
                
                if count >= provider_count:
                    logger.warning(f"Potential rapid account linking detected: user {user_id} ({count} providers in 1 hour)")
                    OAuthAbuseDetector._log_abuse_attempt(
                        user_id=user_id,
                        provider='multiple',
                        abuse_type='rapid_linking',
                        details=f"{count} accounts linked in 1 hour"
                    )
                    return True
        
        except Exception as e:
            logger.error(f"Error detecting rapid account linking: {e}", exc_info=True)
        
        return False
    
    @staticmethod
    def _log_abuse_attempt(
        abuse_type: str,
        details: str,
        ip_address: Optional[str] = None,
        user_id: Optional[str] = None,
        provider: Optional[str] = None
    ):
        """Log abuse attempt to audit log."""
        try:
            with get_db_session() as session:
                audit_log = AuditLog(
                    user_id=user_id,
                    action='oauth_abuse_detected',
                    resource=f'oauth:{provider}' if provider else 'oauth',
                    status='failure',
                    ip_address=ip_address,
                    details=f"{abuse_type}: {details}"
                )
                session.add(audit_log)
                session.commit()
        
        except Exception as e:
            logger.error(f"Error logging abuse attempt: {e}", exc_info=True)
