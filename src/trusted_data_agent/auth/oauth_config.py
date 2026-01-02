"""
OAuth configuration and provider setup using Authlib.

Defines OAuth2 providers (Google, GitHub, Microsoft, Discord, etc.)
and manages OAuth remote app instances.
"""

import logging
import os
from typing import Dict, Optional

logger = logging.getLogger("quart.app")


class OAuthProvider:
    """Base OAuth provider configuration."""
    
    def __init__(
        self,
        name: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        authorize_url: str = "",
        access_token_url: str = "",
        userinfo_url: str = "",
        scopes: list = None,
    ):
        """
        Initialize OAuth provider.
        
        Args:
            name: Provider name (e.g., 'google', 'github')
            client_id: OAuth client ID (from environment if not provided)
            client_secret: OAuth client secret (from environment if not provided)
            authorize_url: Authorization endpoint
            access_token_url: Token endpoint
            userinfo_url: User info endpoint
            scopes: List of scopes to request
        """
        self.name = name
        self.client_id = client_id or os.getenv(f'OAUTH_{name.upper()}_CLIENT_ID')
        self.client_secret = client_secret or os.getenv(f'OAUTH_{name.upper()}_CLIENT_SECRET')
        self.authorize_url = authorize_url
        self.access_token_url = access_token_url
        self.userinfo_url = userinfo_url
        self.scopes = scopes or ['profile', 'email']
    
    def is_configured(self) -> bool:
        """Check if provider has required credentials."""
        return bool(self.client_id and self.client_secret)


# Define supported OAuth providers
OAUTH_PROVIDERS: Dict[str, OAuthProvider] = {
    'google': OAuthProvider(
        name='google',
        authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
        access_token_url='https://oauth2.googleapis.com/token',
        userinfo_url='https://openidconnect.googleapis.com/v1/userinfo',
        scopes=['openid', 'profile', 'email'],
    ),
    'github': OAuthProvider(
        name='github',
        authorize_url='https://github.com/login/oauth/authorize',
        access_token_url='https://github.com/login/oauth/access_token',
        userinfo_url='https://api.github.com/user',
        scopes=['user:email', 'read:user'],
    ),
    'microsoft': OAuthProvider(
        name='microsoft',
        authorize_url='https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
        access_token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
        userinfo_url='https://graph.microsoft.com/v1.0/me',
        scopes=['openid', 'profile', 'email'],
    ),
    'discord': OAuthProvider(
        name='discord',
        authorize_url='https://discord.com/api/oauth2/authorize',
        access_token_url='https://discord.com/api/oauth2/token',
        userinfo_url='https://discord.com/api/users/@me',
        scopes=['identify', 'email'],
    ),
    'okta': OAuthProvider(
        name='okta',
        # Note: Okta domain needs to be configured via environment
        authorize_url=os.getenv('OKTA_DOMAIN', 'https://example.okta.com') + '/oauth2/v1/authorize',
        access_token_url=os.getenv('OKTA_DOMAIN', 'https://example.okta.com') + '/oauth2/v1/token',
        userinfo_url=os.getenv('OKTA_DOMAIN', 'https://example.okta.com') + '/oauth2/v1/userinfo',
        scopes=['openid', 'profile', 'email'],
    ),
}


def get_configured_providers() -> Dict[str, OAuthProvider]:
    """
    Get list of configured OAuth providers.
    
    Returns:
        Dictionary of provider names to configured OAuthProvider instances
    """
    configured = {}
    for name, provider in OAUTH_PROVIDERS.items():
        if provider.is_configured():
            configured[name] = provider
            logger.info(f"OAuth provider '{name}' is configured")
        else:
            logger.debug(f"OAuth provider '{name}' is not configured (missing credentials)")
    
    return configured


def get_provider(name: str) -> Optional[OAuthProvider]:
    """
    Get a specific OAuth provider.
    
    Args:
        name: Provider name
        
    Returns:
        OAuthProvider instance if configured, None otherwise
    """
    provider = OAUTH_PROVIDERS.get(name.lower())
    if provider and provider.is_configured():
        return provider
    return None


class OAuthConfig:
    """OAuth configuration for Quart application."""
    
    # OAuth settings
    OAUTH_INSECURE_TRANSPORT = os.getenv('OAUTH_INSECURE_TRANSPORT', 'False').lower() == 'true'
    OAUTH_CACHE_TYPE = 'simple'
    
    # HTTPS redirect (required for production)
    OAUTH_HTTPS_ONLY = os.getenv('OAUTH_HTTPS_ONLY', 'True').lower() == 'true'
    
    # Callback URL (should be set in environment for production)
    # Format: https://yourdomain.com/api/v1/auth/oauth/{provider}/callback
    OAUTH_CALLBACK_URL = os.getenv(
        'OAUTH_CALLBACK_URL',
        'http://localhost:8000/api/v1/auth/oauth/{provider}/callback'
    )
    
    # Session configuration
    OAUTH_SESSION_COOKIE_SECURE = os.getenv('OAUTH_SESSION_COOKIE_SECURE', 'True').lower() == 'true'
    OAUTH_SESSION_COOKIE_HTTPONLY = True
    OAUTH_SESSION_COOKIE_SAMESITE = 'Lax'
    
    @classmethod
    def get_callback_url(cls, provider: str) -> str:
        """Get OAuth callback URL for a specific provider."""
        return cls.OAUTH_CALLBACK_URL.format(provider=provider.lower())
    
    @classmethod
    def validate(cls) -> bool:
        """Validate OAuth configuration."""
        if cls.OAUTH_HTTPS_ONLY and 'http://' in cls.OAUTH_CALLBACK_URL:
            logger.warning(
                "OAuth callback URL uses HTTP but OAUTH_HTTPS_ONLY is True. "
                "This may cause security issues in production."
            )
        
        configured_providers = get_configured_providers()
        if not configured_providers:
            logger.warning("No OAuth providers are configured. OAuth functionality will be disabled.")
            return False
        
        logger.info(f"OAuth configuration validated. Configured providers: {list(configured_providers.keys())}")
        return True


def get_oauth_metadata_template(provider: str) -> dict:
    """
    Get template for OAuth metadata storage.
    
    Returns:
        Dictionary with common OAuth metadata fields
    """
    templates = {
        'google': {
            'sub': None,
            'email_verified': False,
            'locale': None,
        },
        'github': {
            'id': None,
            'login': None,
            'type': None,
            'public_repos': 0,
        },
        'microsoft': {
            'id': None,
            'userPrincipalName': None,
            'jobTitle': None,
        },
        'discord': {
            'id': None,
            'discriminator': None,
            'verified': False,
            'locale': None,
        },
        'okta': {
            'sub': None,
            'email_verified': False,
            'locale': None,
        },
    }
    
    return templates.get(provider.lower(), {})
