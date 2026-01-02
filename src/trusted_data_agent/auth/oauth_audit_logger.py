"""
Enhanced OAuth audit logging and analytics.

Provides detailed logging for OAuth operations for security monitoring and analytics.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import AuditLog

logger = logging.getLogger("quart.app")


class OAuthAuditLogger:
    """Enhanced audit logging for OAuth operations."""
    
    @staticmethod
    def log_oauth_initiation(
        provider: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        return_to: Optional[str] = None
    ):
        """
        Log OAuth flow initiation.
        
        Args:
            provider: OAuth provider name
            ip_address: Client IP address
            user_agent: Client user agent
            return_to: Return URL after OAuth callback
        """
        OAuthAuditLogger._log_event(
            action='oauth_initiate',
            provider=provider,
            status='success',
            ip_address=ip_address,
            user_agent=user_agent,
            details=json.dumps({
                'flow': 'login',
                'return_to': return_to
            })
        )
    
    @staticmethod
    def log_oauth_callback(
        provider: str,
        user_id: Optional[str] = None,
        is_new_user: bool = False,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        Log OAuth callback processing.
        
        Args:
            provider: OAuth provider name
            user_id: User ID (if successful)
            is_new_user: Whether user was newly created
            ip_address: Client IP address
            user_agent: Client user agent
            success: Whether callback was successful
            error: Error message if unsuccessful
        """
        OAuthAuditLogger._log_event(
            action='oauth_callback',
            provider=provider,
            user_id=user_id,
            status='success' if success else 'failure',
            ip_address=ip_address,
            user_agent=user_agent,
            details=json.dumps({
                'new_user': is_new_user,
                'error': error
            })
        )
    
    @staticmethod
    def log_oauth_login(
        provider: str,
        user_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        is_new_user: bool = False
    ):
        """
        Log successful OAuth login.
        
        Args:
            provider: OAuth provider name
            user_id: User ID
            ip_address: Client IP address
            user_agent: Client user agent
            is_new_user: Whether this was the user's first login
        """
        OAuthAuditLogger._log_event(
            action='oauth_login',
            provider=provider,
            user_id=user_id,
            status='success',
            ip_address=ip_address,
            user_agent=user_agent,
            details=json.dumps({
                'new_user': is_new_user,
                'event': 'successful_login'
            })
        )
    
    @staticmethod
    def log_oauth_link(
        provider: str,
        user_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        Log OAuth account linking.
        
        Args:
            provider: OAuth provider name
            user_id: User ID
            ip_address: Client IP address
            user_agent: Client user agent
            success: Whether linking was successful
            error: Error message if unsuccessful
        """
        OAuthAuditLogger._log_event(
            action='oauth_link',
            provider=provider,
            user_id=user_id,
            status='success' if success else 'failure',
            ip_address=ip_address,
            user_agent=user_agent,
            details=json.dumps({
                'error': error
            })
        )
    
    @staticmethod
    def log_oauth_unlink(
        provider: str,
        user_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        Log OAuth account unlinking.
        
        Args:
            provider: OAuth provider name
            user_id: User ID
            ip_address: Client IP address
            user_agent: Client user agent
            success: Whether unlinking was successful
            error: Error message if unsuccessful
        """
        OAuthAuditLogger._log_event(
            action='oauth_unlink',
            provider=provider,
            user_id=user_id,
            status='success' if success else 'failure',
            ip_address=ip_address,
            user_agent=user_agent,
            details=json.dumps({
                'error': error
            })
        )
    
    @staticmethod
    def log_email_verification(
        user_id: str,
        email: str,
        verification_type: str = 'oauth',
        success: bool = True,
        error: Optional[str] = None,
        ip_address: Optional[str] = None
    ):
        """
        Log email verification event.
        
        Args:
            user_id: User ID
            email: Email being verified
            verification_type: Type of verification (oauth, signup, email_change)
            success: Whether verification was successful
            error: Error message if unsuccessful
            ip_address: Client IP address
        """
        OAuthAuditLogger._log_event(
            action='email_verification',
            provider=verification_type,
            user_id=user_id,
            status='success' if success else 'failure',
            ip_address=ip_address,
            details=json.dumps({
                'email': email,
                'type': verification_type,
                'error': error
            })
        )
    
    @staticmethod
    def log_account_merge(
        provider: str,
        user_id: str,
        merged_from: Optional[str] = None,
        ip_address: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        Log account merging event.
        
        Args:
            provider: OAuth provider name
            user_id: Target user ID
            merged_from: Source account identifier (if merging existing accounts)
            ip_address: Client IP address
            success: Whether merge was successful
            error: Error message if unsuccessful
        """
        OAuthAuditLogger._log_event(
            action='oauth_account_merge',
            provider=provider,
            user_id=user_id,
            status='success' if success else 'failure',
            ip_address=ip_address,
            details=json.dumps({
                'merged_from': merged_from,
                'error': error
            })
        )
    
    @staticmethod
    def log_rate_limit_exceeded(
        provider: str,
        operation: str,
        identifier: str,  # IP or user ID
        ip_address: Optional[str] = None,
        user_id: Optional[str] = None
    ):
        """
        Log rate limit exceeded event.
        
        Args:
            provider: OAuth provider name
            operation: Operation type (login, link, callback)
            identifier: IP address or user ID
            ip_address: Client IP address
            user_id: User ID if applicable
        """
        OAuthAuditLogger._log_event(
            action='oauth_rate_limit_exceeded',
            provider=provider,
            user_id=user_id,
            status='failure',
            ip_address=ip_address,
            details=json.dumps({
                'operation': operation,
                'identifier': identifier
            })
        )
    
    @staticmethod
    def log_suspicious_activity(
        activity_type: str,
        provider: str,
        details: Dict[str, Any],
        ip_address: Optional[str] = None,
        user_id: Optional[str] = None
    ):
        """
        Log suspicious activity detection.
        
        Args:
            activity_type: Type of suspicious activity (brute_force, enumeration, etc.)
            provider: OAuth provider name
            details: Additional details about the activity
            ip_address: Client IP address
            user_id: User ID if applicable
        """
        OAuthAuditLogger._log_event(
            action='oauth_suspicious_activity',
            provider=provider,
            user_id=user_id,
            status='failure',
            ip_address=ip_address,
            details=json.dumps({
                'activity_type': activity_type,
                **details
            })
        )
    
    @staticmethod
    def _log_event(
        action: str,
        provider: str,
        status: str,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[str] = None
    ):
        """
        Log an OAuth event to the audit log.
        
        Args:
            action: Action type (oauth_login, oauth_link, etc.)
            provider: OAuth provider name
            status: Status (success, failure)
            user_id: User ID if applicable
            ip_address: Client IP address
            user_agent: Client user agent
            details: Additional details (JSON string)
        """
        try:
            with get_db_session() as session:
                audit_log = AuditLog(
                    action=action,
                    resource=f'oauth:{provider}',
                    status=status,
                    user_id=user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details=details
                )
                session.add(audit_log)
                session.commit()
                
                log_level = 'info' if status == 'success' else 'warning'
                log_message = f"OAuth audit: {action} for {provider} - {status}"
                if user_id:
                    log_message += f" (user: {user_id})"
                
                getattr(logger, log_level)(log_message)
        
        except Exception as e:
            logger.error(f"Error logging OAuth event: {e}", exc_info=True)


class OAuthAnalytics:
    """Analytics for OAuth usage patterns."""
    
    @staticmethod
    def get_oauth_stats(days: int = 7) -> Dict[str, Any]:
        """
        Get OAuth usage statistics.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Dictionary with OAuth statistics
        """
        try:
            from datetime import timedelta
            
            with get_db_session() as session:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                
                # Get all OAuth-related events
                events = session.query(AuditLog).filter(
                    AuditLog.action.like('oauth_%'),
                    AuditLog.timestamp >= cutoff_date
                ).all()
                
                # Process statistics
                stats = {
                    'total_events': len(events),
                    'successful_logins': 0,
                    'failed_logins': 0,
                    'account_links': 0,
                    'new_users': 0,
                    'by_provider': {},
                    'unique_users': set(),
                    'unique_ips': set()
                }
                
                for event in events:
                    # Collect unique users and IPs
                    if event.user_id:
                        stats['unique_users'].add(event.user_id)
                    if event.ip_address:
                        stats['unique_ips'].add(event.ip_address)
                    
                    # Extract provider
                    provider = event.resource.split(':')[1] if ':' in event.resource else 'unknown'
                    if provider not in stats['by_provider']:
                        stats['by_provider'][provider] = {'success': 0, 'failure': 0}
                    
                    # Count by action
                    if 'login' in event.action:
                        if event.status == 'success':
                            stats['successful_logins'] += 1
                        else:
                            stats['failed_logins'] += 1
                    elif 'link' in event.action:
                        stats['account_links'] += 1
                    
                    # Count by provider status
                    stats['by_provider'][provider][event.status] += 1
                
                # Convert sets to counts
                stats['unique_users'] = len(stats['unique_users'])
                stats['unique_ips'] = len(stats['unique_ips'])
                
                return stats
        
        except Exception as e:
            logger.error(f"Error generating OAuth statistics: {e}", exc_info=True)
            return {}
    
    @staticmethod
    def get_provider_popularity() -> Dict[str, int]:
        """
        Get popularity ranking of OAuth providers.
        
        Returns:
            Dictionary mapping provider names to usage count
        """
        try:
            from datetime import timedelta
            
            with get_db_session() as session:
                # Count OAuth logins by provider in last 30 days
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
                
                logins = session.query(
                    AuditLog.resource,
                    AuditLog
                ).filter(
                    AuditLog.action == 'oauth_login',
                    AuditLog.status == 'success',
                    AuditLog.timestamp >= cutoff_date
                ).all()
                
                popularity = {}
                for log in logins:
                    provider = log[0].split(':')[1] if ':' in log[0] else 'unknown'
                    popularity[provider] = popularity.get(provider, 0) + 1
                
                return dict(sorted(popularity.items(), key=lambda x: x[1], reverse=True))
        
        except Exception as e:
            logger.error(f"Error calculating provider popularity: {e}", exc_info=True)
            return {}
