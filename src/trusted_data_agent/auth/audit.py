"""
Audit logging for security and compliance.

Records all security-relevant events including authentication, authorization,
configuration changes, and API access.
"""

import os
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from quart import request

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import AuditLog

logger = logging.getLogger("quart.app")

# Configuration
AUDIT_LOGGING_ENABLED = os.environ.get('TDA_AUDIT_LOGGING_ENABLED', 'true').lower() == 'true'


def _get_client_info() -> tuple[str, str]:
    """
    Extract client IP and user agent from request.
    
    Returns:
        Tuple of (ip_address, user_agent)
    """
    # Get IP address
    ip_address = 'unknown'
    try:
        if 'X-Forwarded-For' in request.headers:
            ip_address = request.headers['X-Forwarded-For'].split(',')[0].strip()
        elif 'X-Real-IP' in request.headers:
            ip_address = request.headers['X-Real-IP']
        elif request.remote_addr:
            ip_address = request.remote_addr
    except:
        pass
    
    # Get user agent
    user_agent = request.headers.get('User-Agent', 'unknown') if request else 'unknown'
    
    return ip_address, user_agent


def log_audit_event(
    user_id: Optional[str],
    action: str,
    details: str,
    success: bool = True,
    resource: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Log an audit event to the database.
    
    Args:
        user_id: User ID (None for anonymous events)
        action: Action type (login, logout, configure, execute, etc.)
        details: Human-readable description of the event
        success: Whether the action was successful
        resource: Optional resource identifier (endpoint, session_id, etc.)
        ip_address: Optional IP address (auto-detected from request if None)
        user_agent: Optional user agent (auto-detected from request if None)
        metadata: Optional additional metadata as dictionary
        
    Returns:
        True if logged successfully, False otherwise
    """
    if not AUDIT_LOGGING_ENABLED:
        return True
    
    try:
        # Auto-detect client info if not provided
        if ip_address is None or user_agent is None:
            try:
                detected_ip, detected_ua = _get_client_info()
                ip_address = ip_address or detected_ip
                user_agent = user_agent or detected_ua
            except:
                ip_address = ip_address or 'unknown'
                user_agent = user_agent or 'unknown'
        
        # Create audit log entry
        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            status='success' if success else 'failure',
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
            metadata=json.dumps(metadata) if metadata else None
        )
        
        # Store in database
        with get_db_session() as session:
            session.add(audit_log)
        
        # Log to application logger as well (for immediate visibility)
        log_level = logging.INFO if success else logging.WARNING
        logger.log(
            log_level,
            f"AUDIT: {action} - User: {user_id or 'anonymous'} - {details} - Status: {'success' if success else 'failure'}"
        )
        
        return True
    
    except Exception as e:
        logger.error(f"Failed to log audit event: {e}", exc_info=True)
        return False


def log_login_attempt(user_id: str, username: str, success: bool, reason: Optional[str] = None):
    """Log a login attempt."""
    details = f"Login attempt for user '{username}'"
    if not success and reason:
        details += f": {reason}"
    
    log_audit_event(
        user_id=user_id if success else None,
        action='login_attempt',
        details=details,
        success=success,
        resource='/api/v1/auth/login'
    )


def log_login_success(user_id: str, username: str):
    """Log a successful login."""
    log_audit_event(
        user_id=user_id,
        action='login_success',
        details=f"User '{username}' logged in successfully",
        success=True,
        resource='/api/v1/auth/login'
    )


def log_login_failure(username: str, reason: str):
    """Log a failed login."""
    log_audit_event(
        user_id=None,
        action='login_failure',
        details=f"Failed login attempt for '{username}': {reason}",
        success=False,
        resource='/api/v1/auth/login'
    )


def log_logout(user_id: str, username: str):
    """Log a logout event."""
    log_audit_event(
        user_id=user_id,
        action='logout',
        details=f"User '{username}' logged out",
        success=True,
        resource='/api/v1/auth/logout'
    )


def log_registration(user_id: str, username: str, success: bool, reason: Optional[str] = None):
    """Log a registration attempt."""
    details = f"Registration for user '{username}'"
    if not success and reason:
        details += f": {reason}"
    
    log_audit_event(
        user_id=user_id if success else None,
        action='registration',
        details=details,
        success=success,
        resource='/api/v1/auth/register'
    )


def log_password_change(user_id: str, username: str, success: bool):
    """Log a password change."""
    log_audit_event(
        user_id=user_id,
        action='password_change',
        details=f"Password changed for user '{username}'",
        success=success,
        resource='/api/v1/auth/change-password'
    )


def log_configuration_change(user_id: str, provider: str, details: str):
    """Log a configuration change."""
    log_audit_event(
        user_id=user_id,
        action='configuration_change',
        details=f"Configuration updated: {provider} - {details}",
        success=True,
        resource='/api/configure'
    )


def log_prompt_execution(user_id: str, session_id: str, prompt_summary: str):
    """Log a prompt execution."""
    log_audit_event(
        user_id=user_id,
        action='prompt_execution',
        details=f"Executed prompt in session {session_id}: {prompt_summary[:100]}",
        success=True,
        resource=f'/api/agent?session_id={session_id}'
    )


def log_session_access(user_id: str, session_id: str, action: str):
    """Log session access (create, load, delete)."""
    log_audit_event(
        user_id=user_id,
        action=f'session_{action}',
        details=f"Session {action}: {session_id}",
        success=True,
        resource=f'/api/sessions/{session_id}'
    )


def log_credential_change(user_id: str, provider: str, action: str):
    """Log credential storage/deletion."""
    log_audit_event(
        user_id=user_id,
        action='credential_change',
        details=f"Credentials {action} for provider: {provider}",
        success=True,
        resource=f'/api/credentials/{provider}'
    )


def log_admin_action(admin_user_id: str, action: str, target_user_id: str, details: str):
    """Log an administrative action."""
    log_audit_event(
        user_id=admin_user_id,
        action=f'admin_{action}',
        details=f"Admin action on user {target_user_id}: {details}",
        success=True,
        resource=f'/api/admin/users/{target_user_id}',
        metadata={'target_user_id': target_user_id}
    )


def log_api_access(user_id: Optional[str], endpoint: str, method: str, status_code: int):
    """Log general API access."""
    log_audit_event(
        user_id=user_id,
        action='api_access',
        details=f"{method} {endpoint} - Status: {status_code}",
        success=status_code < 400,
        resource=endpoint
    )


def log_rate_limit_exceeded(identifier: str, endpoint: str):
    """Log rate limit violations."""
    # Extract actual user_id if identifier is like "user:xyz"
    user_id = None
    if identifier.startswith('user:'):
        user_id = identifier[5:]  # Skip "user:" prefix
    elif not identifier.startswith('ip:'):
        user_id = identifier
    
    log_audit_event(
        user_id=user_id,
        action='rate_limit_exceeded',
        details=f"Rate limit exceeded for {identifier} on {endpoint}",
        success=False,
        resource=endpoint
    )


def log_security_event(user_id: Optional[str], event_type: str, details: str, severity: str = 'warning'):
    """
    Log a security event.
    
    Args:
        user_id: User ID if applicable
        event_type: Type of security event (sql_injection, xss_attempt, etc.)
        details: Description of the security event
        severity: Severity level (info, warning, critical)
    """
    log_audit_event(
        user_id=user_id,
        action=f'security_{event_type}',
        details=details,
        success=False,
        metadata={'severity': severity}
    )
    
    # Also log to application logger at appropriate level
    if severity == 'critical':
        logger.error(f"SECURITY ALERT: {event_type} - {details}")
    else:
        logger.warning(f"SECURITY WARNING: {event_type} - {details}")


def get_user_audit_logs(
    user_id: str,
    limit: int = 100,
    offset: int = 0,
    action_filter: Optional[str] = None
) -> list[Dict[str, Any]]:
    """
    Retrieve audit logs for a specific user.
    
    Args:
        user_id: User's unique identifier
        limit: Maximum number of records to return
        offset: Number of records to skip
        action_filter: Optional action type filter
        
    Returns:
        List of audit log dictionaries
    """
    try:
        with get_db_session() as session:
            query = session.query(AuditLog).filter_by(user_id=user_id)
            
            if action_filter:
                query = query.filter_by(action=action_filter)
            
            query = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit)
            
            logs = []
            for log in query.all():
                # Parse metadata if it's a string, otherwise use as-is
                metadata = log.metadata
                if metadata and isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except json.JSONDecodeError:
                        metadata = None
                
                logs.append({
                    'id': log.id,
                    'action': log.action,
                    'resource': log.resource,
                    'status': log.status,
                    'details': log.details,
                    'ip_address': log.ip_address,
                    'timestamp': log.timestamp.isoformat(),
                    'metadata': metadata
                })
            
            return logs
    
    except Exception as e:
        logger.error(f"Failed to retrieve audit logs for user {user_id}: {e}", exc_info=True)
        return []


def cleanup_old_audit_logs(days: int = 90) -> int:
    """
    Delete audit logs older than specified days (for GDPR compliance/storage management).
    
    Args:
        days: Number of days to retain logs
        
    Returns:
        Number of logs deleted
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        with get_db_session() as session:
            result = session.query(AuditLog).filter(
                AuditLog.timestamp < cutoff
            ).delete()
            
            logger.info(f"Cleaned up {result} audit log(s) older than {days} days")
            return result
    
    except Exception as e:
        logger.error(f"Failed to cleanup old audit logs: {e}", exc_info=True)
        return 0
