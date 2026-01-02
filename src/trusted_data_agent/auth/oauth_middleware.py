"""
OAuth middleware for Quart integration with Authlib.

Provides async-compatible OAuth flow helpers and CSRF protection for Quart.
"""

import logging
import secrets
import json
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple

from quart import request, session, abort, url_for

from trusted_data_agent.auth.oauth_config import get_provider, OAuthConfig

logger = logging.getLogger("quart.app")


class OAuthSession:
    """Manages OAuth session state with CSRF protection."""
    
    STATE_SESSION_KEY = 'oauth_state'
    NONCE_SESSION_KEY = 'oauth_nonce'
    PROVIDER_SESSION_KEY = 'oauth_provider'
    RETURN_TO_SESSION_KEY = 'oauth_return_to'
    
    STATE_EXPIRY_MINUTES = 15
    
    @staticmethod
    async def generate_state(provider: str, return_to: Optional[str] = None) -> str:
        """
        Generate and store OAuth state for CSRF protection.
        
        Args:
            provider: OAuth provider name
            return_to: Optional URL to return to after OAuth flow
            
        Returns:
            State string for authorization request
        """
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        
        # Store in session
        session[OAuthSession.STATE_SESSION_KEY] = state
        session[OAuthSession.NONCE_SESSION_KEY] = nonce
        session[OAuthSession.PROVIDER_SESSION_KEY] = provider
        if return_to:
            session[OAuthSession.RETURN_TO_SESSION_KEY] = return_to
        
        # Set session expiry
        session.permanent = True
        
        logger.debug(f"Generated OAuth state for {provider}")
        return state
    
    @staticmethod
    async def verify_state(expected_state: str, provider: str) -> Tuple[bool, Optional[str]]:
        """
        Verify OAuth state parameter for CSRF protection.
        
        Args:
            expected_state: State value from callback
            provider: Expected provider name
            
        Returns:
            Tuple of (is_valid: bool, return_to: Optional[str])
        """
        stored_state = session.get(OAuthSession.STATE_SESSION_KEY)
        stored_provider = session.get(OAuthSession.PROVIDER_SESSION_KEY)
        return_to = session.get(OAuthSession.RETURN_TO_SESSION_KEY)
        
        # Verify state matches
        if not stored_state or stored_state != expected_state:
            logger.warning(f"OAuth state mismatch for {provider}")
            return False, None
        
        # Verify provider matches
        if not stored_provider or stored_provider != provider:
            logger.warning(f"OAuth provider mismatch: expected {provider}, got {stored_provider}")
            return False, None
        
        # Clean up session
        session.pop(OAuthSession.STATE_SESSION_KEY, None)
        session.pop(OAuthSession.NONCE_SESSION_KEY, None)
        session.pop(OAuthSession.PROVIDER_SESSION_KEY, None)
        session.pop(OAuthSession.RETURN_TO_SESSION_KEY, None)
        
        logger.debug(f"OAuth state verified for {provider}")
        return True, return_to
    
    @staticmethod
    def get_return_to() -> Optional[str]:
        """Get the return_to URL from session."""
        return session.get(OAuthSession.RETURN_TO_SESSION_KEY)
    
    @staticmethod
    def clear_session():
        """Clear OAuth session data."""
        session.pop(OAuthSession.STATE_SESSION_KEY, None)
        session.pop(OAuthSession.NONCE_SESSION_KEY, None)
        session.pop(OAuthSession.PROVIDER_SESSION_KEY, None)
        session.pop(OAuthSession.RETURN_TO_SESSION_KEY, None)


class OAuthAuthorizationBuilder:
    """Builds OAuth authorization URLs."""
    
    @staticmethod
    async def build_authorization_url(
        provider_name: str,
        return_to: Optional[str] = None,
        include_offline_access: bool = False
    ) -> Optional[str]:
        """
        Build OAuth authorization URL.
        
        Args:
            provider_name: OAuth provider name
            return_to: Optional URL to return to after OAuth flow
            include_offline_access: Request offline access (refresh token)
            
        Returns:
            Authorization URL string, or None if provider not configured
        """
        provider = get_provider(provider_name)
        if not provider:
            logger.error(f"OAuth provider '{provider_name}' is not configured")
            return None
        
        # Generate state
        state = await OAuthSession.generate_state(provider_name, return_to)
        
        # Build authorization URL
        # Get the callback URL from config
        callback_url = OAuthConfig.get_callback_url(provider_name)
        
        params = {
            'client_id': provider.client_id,
            'redirect_uri': callback_url,
            'response_type': 'code',
            'scope': ' '.join(provider.scopes),
            'state': state,
        }
        
        # Add nonce for OpenID Connect providers
        if 'openid' in provider.scopes:
            nonce = secrets.token_urlsafe(32)
            session[OAuthSession.NONCE_SESSION_KEY] = nonce
            params['nonce'] = nonce
        
        # Request offline access if needed
        if include_offline_access:
            params['access_type'] = 'offline'  # Google
            params['prompt'] = 'consent'  # Google, Microsoft
        
        auth_url = f"{provider.authorize_url}?{urlencode(params)}"
        
        logger.debug(f"Built authorization URL for {provider_name}")
        return auth_url
    
    @staticmethod
    async def build_authorization_url_for_linking(
        provider_name: str,
        user_id: str
    ) -> Optional[str]:
        """
        Build OAuth authorization URL for linking to existing account.
        
        Args:
            provider_name: OAuth provider name
            user_id: ID of user to link to
            
        Returns:
            Authorization URL string, or None if provider not configured
        """
        # Use a callback that handles linking instead of login
        return await OAuthAuthorizationBuilder.build_authorization_url(
            provider_name,
            return_to=f"/api/v1/auth/profile?tab=connected_accounts"
        )


class OAuthCallbackValidator:
    """Validates OAuth callback parameters."""
    
    @staticmethod
    async def validate_callback_request(provider_name: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Validate OAuth callback request from provider.
        
        Args:
            provider_name: OAuth provider name
            
        Returns:
            Tuple of (is_valid, code, state, error_message)
        """
        # Get parameters from query string
        args = request.args
        code = args.get('code')
        state = args.get('state')
        error = args.get('error')
        error_description = args.get('error_description')
        
        # Check for error from provider
        if error:
            error_msg = f"OAuth provider returned error: {error}"
            if error_description:
                error_msg += f" - {error_description}"
            logger.warning(error_msg)
            return False, None, None, error_msg
        
        # Check for authorization code
        if not code:
            error_msg = "Missing authorization code in callback"
            logger.warning(f"{error_msg} from {provider_name}")
            return False, None, None, error_msg
        
        # Check for state
        if not state:
            error_msg = "Missing state parameter in callback"
            logger.warning(f"{error_msg} from {provider_name}")
            return False, None, None, error_msg
        
        # Verify state for CSRF protection
        is_valid, return_to = await OAuthSession.verify_state(state, provider_name)
        if not is_valid:
            error_msg = "Invalid or expired state parameter"
            logger.warning(f"{error_msg} for {provider_name}")
            return False, None, None, error_msg
        
        logger.info(f"Validated OAuth callback from {provider_name}")
        return True, code, state, None
    
    @staticmethod
    def get_callback_redirect_uri(provider_name: str) -> str:
        """
        Get the callback redirect URI for a provider.
        
        Args:
            provider_name: OAuth provider name
            
        Returns:
            Callback URI
        """
        return OAuthConfig.get_callback_url(provider_name)


class OAuthErrorHandler:
    """Handles OAuth errors gracefully."""
    
    @staticmethod
    def handle_oauth_error(error_message: str, status_code: int = 400) -> Dict:
        """
        Create error response for OAuth failures.
        
        Args:
            error_message: Error message
            status_code: HTTP status code
            
        Returns:
            Error response dictionary
        """
        logger.error(f"OAuth error: {error_message}")
        return {
            'error': error_message,
            'status_code': status_code
        }
    
    @staticmethod
    def log_oauth_event(
        provider: str,
        event_type: str,
        user_id: Optional[str] = None,
        success: bool = True,
        details: Optional[str] = None
    ):
        """
        Log OAuth events for audit purposes.
        
        Args:
            provider: OAuth provider name
            event_type: Type of event (e.g., 'login', 'link', 'unlink')
            user_id: Optional user ID
            success: Whether event was successful
            details: Optional additional details
        """
        from trusted_data_agent.auth.audit import log_audit_event
        
        status = 'success' if success else 'failure'
        message = f"OAuth {event_type}: {provider}"
        if details:
            message += f" - {details}"
        
        log_audit_event(
            action=f'oauth_{event_type}',
            resource=f'oauth:{provider}',
            status=status,
            details=message,
            user_id=user_id
        )


async def get_client_ip() -> Optional[str]:
    """Get client IP address from request."""
    # Check X-Forwarded-For header first (for proxied requests)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    
    # Fall back to remote address
    return request.remote_addr


def validate_oauth_provider(provider_name: str) -> bool:
    """
    Validate that an OAuth provider is configured.
    
    Args:
        provider_name: OAuth provider name
        
    Returns:
        True if provider is configured, False otherwise
    """
    provider = get_provider(provider_name)
    return provider is not None
