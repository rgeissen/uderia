"""
OAuth handler functions for managing OAuth flow and user synchronization.

Handles token exchange, user creation/update, and JWT generation from OAuth responses.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, Any

import httpx

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, OAuthAccount
from trusted_data_agent.auth.oauth_config import get_provider, get_oauth_metadata_template
from trusted_data_agent.auth.security import generate_auth_token
from trusted_data_agent.auth.email_verification import (
    EmailVerificationService,
    EmailVerificationValidator
)
from trusted_data_agent.auth.account_merge import AccountMergeService

logger = logging.getLogger("quart.app")


class OAuthHandler:
    """Handles OAuth token exchange and user synchronization."""
    
    def __init__(self, provider_name: str):
        """
        Initialize OAuth handler for a specific provider.
        
        Args:
            provider_name: Name of the OAuth provider (e.g., 'google', 'github')
        """
        self.provider_name = provider_name.lower()
        self.provider = get_provider(self.provider_name)
        
        if not self.provider:
            raise ValueError(f"OAuth provider '{provider_name}' is not configured")
    
    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
        """
        Exchange authorization code for access token.
        
        Args:
            code: Authorization code from OAuth provider
            redirect_uri: Redirect URI used in the authorization request
            
        Returns:
            Token response dictionary with access_token, or None on failure
        """
        try:
            async with httpx.AsyncClient() as client:
                data = {
                    'code': code,
                    'client_id': self.provider.client_id,
                    'client_secret': self.provider.client_secret,
                    'redirect_uri': redirect_uri,
                    'grant_type': 'authorization_code',
                }
                
                response = await client.post(
                    self.provider.access_token_url,
                    data=data,
                    timeout=10.0
                )
                response.raise_for_status()
                
                token_data = response.json()
                logger.info(f"Successfully exchanged code for {self.provider_name} access token")
                return token_data
        
        except httpx.HTTPError as e:
            logger.error(f"HTTP error during token exchange with {self.provider_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error exchanging code for {self.provider_name}: {e}", exc_info=True)
            return None
    
    async def get_user_info(self, access_token: str) -> Optional[Dict[str, Any]]:
        """
        Fetch user information from OAuth provider.
        
        Args:
            access_token: Access token from OAuth provider
            
        Returns:
            User info dictionary, or None on failure
        """
        try:
            async with httpx.AsyncClient() as client:
                headers = {'Authorization': f'Bearer {access_token}'}
                
                response = await client.get(
                    self.provider.userinfo_url,
                    headers=headers,
                    timeout=10.0
                )
                response.raise_for_status()
                
                user_info = response.json()
                logger.info(f"Successfully fetched user info from {self.provider_name}")
                return user_info
        
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching user info from {self.provider_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching user info from {self.provider_name}: {e}", exc_info=True)
            return None
    
    def _extract_user_info(self, provider_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract standardized user info from provider-specific response.
        
        Args:
            provider_data: Raw user info from OAuth provider
            
        Returns:
            Dictionary with 'email', 'name', 'picture_url' keys
        """
        extractors = {
            'google': self._extract_google_info,
            'github': self._extract_github_info,
            'microsoft': self._extract_microsoft_info,
            'discord': self._extract_discord_info,
            'okta': self._extract_okta_info,
        }
        
        extractor = extractors.get(self.provider_name)
        if extractor:
            return extractor(provider_data)
        
        # Fallback for unknown providers
        return {
            'provider_id': provider_data.get('id') or provider_data.get('sub'),
            'email': provider_data.get('email'),
            'name': provider_data.get('name'),
            'picture_url': provider_data.get('picture') or provider_data.get('avatar_url'),
        }
    
    @staticmethod
    def _extract_google_info(data: Dict) -> Dict[str, str]:
        """Extract Google-specific user info."""
        return {
            'provider_id': data.get('sub'),
            'email': data.get('email'),
            'name': data.get('name'),
            'picture_url': data.get('picture'),
            'email_verified': data.get('email_verified', False),
            'locale': data.get('locale'),
        }
    
    @staticmethod
    def _extract_github_info(data: Dict) -> Dict[str, str]:
        """Extract GitHub-specific user info."""
        return {
            'provider_id': str(data.get('id')),
            'email': data.get('email'),
            'name': data.get('name'),
            'picture_url': data.get('avatar_url'),
            'login': data.get('login'),
            'bio': data.get('bio'),
            'public_repos': data.get('public_repos', 0),
        }
    
    @staticmethod
    def _extract_microsoft_info(data: Dict) -> Dict[str, str]:
        """Extract Microsoft-specific user info."""
        return {
            'provider_id': data.get('id'),
            'email': data.get('userPrincipalName') or data.get('mail'),
            'name': data.get('displayName'),
            'picture_url': None,  # Microsoft Graph doesn't return picture in basic user endpoint
            'job_title': data.get('jobTitle'),
        }
    
    @staticmethod
    def _extract_discord_info(data: Dict) -> Dict[str, str]:
        """Extract Discord-specific user info."""
        avatar_url = None
        if data.get('avatar'):
            avatar_url = f"https://cdn.discordapp.com/avatars/{data.get('id')}/{data.get('avatar')}.png"
        
        return {
            'provider_id': data.get('id'),
            'email': data.get('email'),
            'name': data.get('username'),
            'picture_url': avatar_url,
            'discriminator': data.get('discriminator'),
            'verified': data.get('verified', False),
            'locale': data.get('locale'),
        }
    
    @staticmethod
    def _extract_okta_info(data: Dict) -> Dict[str, str]:
        """Extract Okta-specific user info."""
        return {
            'provider_id': data.get('sub'),
            'email': data.get('email'),
            'name': data.get('name'),
            'picture_url': data.get('picture'),
            'email_verified': data.get('email_verified', False),
            'locale': data.get('locale'),
        }
    
    async def handle_callback(
        self,
        code: str,
        redirect_uri: str,
        state: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Handle OAuth callback and return JWT token + user info.
        
        Complete OAuth flow:
        1. Exchange code for access token
        2. Fetch user info from provider
        3. Find or create user in database
        4. Link OAuth account
        5. Generate JWT token
        
        Args:
            code: Authorization code from provider
            redirect_uri: Redirect URI used in auth request
            state: State parameter (for CSRF protection)
            
        Returns:
            Tuple of (jwt_token, user_dict) on success, (None, None) on failure
        """
        logger.info(f"Processing OAuth callback for {self.provider_name}")
        
        # Step 1: Exchange code for token
        token_response = await self.exchange_code_for_token(code, redirect_uri)
        if not token_response or 'access_token' not in token_response:
            logger.error(f"Failed to get access token for {self.provider_name}")
            return None, None
        
        access_token = token_response['access_token']
        
        # Step 2: Fetch user info
        provider_data = await self.get_user_info(access_token)
        if not provider_data:
            logger.error(f"Failed to fetch user info from {self.provider_name}")
            return None, None
        
        user_info = self._extract_user_info(provider_data)
        provider_id = user_info.get('provider_id')
        
        if not provider_id:
            logger.error(f"Could not extract provider ID from {self.provider_name} response")
            return None, None
        
        # Step 3-5: Sync user and generate token
        try:
            jwt_token, user_dict = await self._sync_user_and_generate_token(
                provider_id=provider_id,
                user_info=user_info,
                provider_data=provider_data,
                ip_address=None  # Should be passed from request context
            )
            
            return jwt_token, user_dict
        
        except Exception as e:
            logger.error(f"Error syncing user for {self.provider_name}: {e}", exc_info=True)
            return None, None
    
    async def _sync_user_and_generate_token(
        self,
        provider_id: str,
        user_info: Dict[str, Any],
        provider_data: Dict[str, Any],
        ip_address: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Sync OAuth account with database user and generate JWT token.
        
        Args:
            provider_id: Provider's unique user ID
            user_info: Extracted user info dictionary
            provider_data: Full provider response (for metadata)
            ip_address: Optional IP address for token tracking
            
        Returns:
            Tuple of (jwt_token, user_dict)
        """
        with get_db_session() as session:
            # Check if OAuth account exists
            oauth_account = session.query(OAuthAccount).filter_by(
                provider=self.provider_name,
                provider_user_id=provider_id
            ).first()
            
            if oauth_account:
                # Update existing OAuth account
                user = oauth_account.user
                oauth_account.last_used_at = datetime.now(timezone.utc)
                oauth_account.provider_email = user_info.get('email')
                oauth_account.provider_name = user_info.get('name')
                oauth_account.provider_picture_url = user_info.get('picture_url')
                
                # Sync email verification status from OAuth provider
                # If provider says email is verified, mark it as verified
                if user_info.get('email_verified') and not user.email_verified:
                    user.email_verified = True
                    logger.info(f"Updated email_verified=True for user {user.id} from {self.provider_name}")
                
                logger.info(f"Updated existing OAuth account for user {user.id}")
            else:
                # Check if user exists by email
                email = user_info.get('email')
                user = None
                
                if email:
                    user = session.query(User).filter_by(email=email).first()
                
                if not user:
                    # Create new user from OAuth data
                    user = self._create_user_from_oauth(user_info)
                    session.add(user)
                    logger.info(f"Created new user from {self.provider_name} OAuth")
                else:
                    logger.info(f"Found existing user {user.id} by email")
                
                # Create OAuth account link
                oauth_account = OAuthAccount(
                    user_id=user.id,
                    provider=self.provider_name,
                    provider_user_id=provider_id,
                    provider_email=user_info.get('email'),
                    provider_name=user_info.get('name'),
                    provider_picture_url=user_info.get('picture_url'),
                    provider_metadata=provider_data,
                )
                session.add(oauth_account)
                logger.info(f"Created OAuth account link for user {user.id}")
            
            # Update user's last login
            user.last_login_at = datetime.now(timezone.utc)
            
            session.commit()
            
            # Generate JWT token
            jwt_token, _ = generate_auth_token(
                user_id=user.id,
                username=user.username,
                ip_address=ip_address
            )
            
            user_dict = user.to_dict()
            
            logger.info(f"Generated JWT token for user {user.id} via {self.provider_name}")
            
            return jwt_token, user_dict
    
    @staticmethod
    def _create_user_from_oauth(user_info: Dict[str, Any]) -> User:
        """
        Create a new User instance from OAuth user info.
        
        Args:
            user_info: Extracted user info dictionary
            
        Returns:
            New User instance (not yet committed)
        """
        import secrets
        
        # Generate username from email or provider name
        email = user_info.get('email', '')
        base_username = email.split('@')[0] if email else user_info.get('name', 'user').lower()
        
        # Ensure unique username
        username = base_username
        counter = 1
        with get_db_session() as session:
            while session.query(User).filter_by(username=username).first():
                username = f"{base_username}_{counter}"
                counter += 1
        
        # Generate a strong random password (user won't need it for OAuth)
        password_placeholder = secrets.token_urlsafe(32)
        
        # Import hash_password here to avoid circular imports
        from trusted_data_agent.auth.security import hash_password
        
        # Email verification status from OAuth provider
        # Google and Microsoft verify emails, so we trust their verification
        email_verified = user_info.get('email_verified', False)
        
        user = User(
            username=username,
            email=email or f"{username}@oauth-placeholder.local",
            password_hash=hash_password(password_placeholder),
            full_name=user_info.get('name', username),
            display_name=user_info.get('name', username),
            is_active=True,
            profile_tier='user',
            email_verified=email_verified,  # Trust OAuth provider's email verification
        )
        
        return user


async def link_oauth_to_existing_user(
    user_id: str,
    provider_name: str,
    code: str,
    redirect_uri: str
) -> Tuple[bool, str]:
    """
    Link an OAuth account to an existing authenticated user.
    
    Args:
        user_id: ID of authenticated user
        provider_name: Name of OAuth provider
        code: Authorization code from provider
        redirect_uri: Redirect URI used in auth request
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        handler = OAuthHandler(provider_name)
        
        # Exchange code for token and get user info
        token_response = await handler.exchange_code_for_token(code, redirect_uri)
        if not token_response or 'access_token' not in token_response:
            return False, "Failed to obtain access token from provider"
        
        provider_data = await handler.get_user_info(token_response['access_token'])
        if not provider_data:
            return False, "Failed to fetch user info from provider"
        
        user_info = handler._extract_user_info(provider_data)
        provider_id = user_info.get('provider_id')
        
        if not provider_id:
            return False, "Could not extract provider ID from response"
        
        # Check if this OAuth account is already linked to another user
        with get_db_session() as session:
            existing_oauth = session.query(OAuthAccount).filter_by(
                provider=provider_name,
                provider_user_id=provider_id
            ).first()
            
            if existing_oauth and existing_oauth.user_id != user_id:
                return False, f"This {provider_name} account is already linked to another user"
            
            # Create or update OAuth account
            if existing_oauth:
                existing_oauth.provider_email = user_info.get('email')
                existing_oauth.provider_name = user_info.get('name')
                existing_oauth.provider_picture_url = user_info.get('picture_url')
                existing_oauth.last_used_at = datetime.now(timezone.utc)
            else:
                oauth_account = OAuthAccount(
                    user_id=user_id,
                    provider=provider_name,
                    provider_user_id=provider_id,
                    provider_email=user_info.get('email'),
                    provider_name=user_info.get('name'),
                    provider_picture_url=user_info.get('picture_url'),
                    provider_metadata=provider_data,
                )
                session.add(oauth_account)
            
            session.commit()
        
        logger.info(f"Successfully linked {provider_name} account to user {user_id}")
        return True, f"Successfully linked {provider_name} account"
    
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        logger.error(f"Error linking OAuth account: {e}", exc_info=True)
        return False, "An error occurred while linking the account"


async def unlink_oauth_from_user(user_id: str, provider_name: str) -> Tuple[bool, str]:
    """
    Unlink an OAuth account from a user.
    
    Args:
        user_id: ID of user
        provider_name: Name of OAuth provider to unlink
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        with get_db_session() as session:
            oauth_account = session.query(OAuthAccount).filter_by(
                user_id=user_id,
                provider=provider_name
            ).first()
            
            if not oauth_account:
                return False, f"No {provider_name} account linked to this user"
            
            session.delete(oauth_account)
            session.commit()
        
        logger.info(f"Unlinked {provider_name} account from user {user_id}")
        return True, f"Successfully unlinked {provider_name} account"
    
    except Exception as e:
        logger.error(f"Error unlinking OAuth account: {e}", exc_info=True)
        return False, "An error occurred while unlinking the account"
