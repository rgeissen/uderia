"""
Account merging and deduplication service.

Handles merging OAuth accounts with existing users who share the same email.
"""

import logging
from typing import Optional, Tuple

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, OAuthAccount

logger = logging.getLogger("quart.app")


class AccountMergeService:
    """Service for managing account merging and deduplication."""
    
    @staticmethod
    def find_existing_user_by_email(email: str) -> Optional[User]:
        """
        Find an existing user with the given email.
        
        Args:
            email: Email address to search for
            
        Returns:
            User if found, None otherwise
        """
        try:
            with get_db_session() as session:
                user = session.query(User).filter_by(email=email.lower()).first()
                return user
        except Exception as e:
            logger.error(f"Error finding user by email: {e}", exc_info=True)
            return None
    
    @staticmethod
    def can_merge_oauth_to_user(
        user_id: str,
        provider_name: str,
        provider_user_id: str
    ) -> Tuple[bool, str]:
        """
        Check if OAuth account can be merged with existing user.
        
        Args:
            user_id: ID of user to merge with
            provider_name: OAuth provider name
            provider_user_id: Provider's unique user ID
            
        Returns:
            Tuple of (can_merge: bool, reason: str)
        """
        try:
            with get_db_session() as session:
                # Check if user exists
                user = session.query(User).filter_by(id=user_id).first()
                if not user:
                    return False, "User not found"
                
                # Check if OAuth account is already linked to this user
                existing_oauth = session.query(OAuthAccount).filter_by(
                    user_id=user_id,
                    provider=provider_name
                ).first()
                
                if existing_oauth:
                    return False, f"{provider_name} account already linked to this user"
                
                # Check if OAuth account is linked to different user
                other_oauth = session.query(OAuthAccount).filter_by(
                    provider=provider_name,
                    provider_user_id=provider_user_id
                ).first()
                
                if other_oauth and other_oauth.user_id != user_id:
                    return False, f"This {provider_name} account is already linked to another user"
                
                return True, "Account can be merged"
        
        except Exception as e:
            logger.error(f"Error checking merge eligibility: {e}", exc_info=True)
            return False, "An error occurred while checking merge eligibility"
    
    @staticmethod
    def merge_oauth_account(
        user_id: str,
        provider_name: str,
        provider_user_id: str,
        provider_email: Optional[str] = None,
        provider_name_str: Optional[str] = None,
        provider_picture_url: Optional[str] = None,
        provider_metadata: Optional[dict] = None
    ) -> Tuple[bool, str]:
        """
        Merge an OAuth account with existing user.
        
        Args:
            user_id: ID of user to merge with
            provider_name: OAuth provider name
            provider_user_id: Provider's unique user ID
            provider_email: Email from provider
            provider_name_str: Name from provider
            provider_picture_url: Profile picture URL
            provider_metadata: Additional metadata from provider
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Check if merge is possible
            can_merge, reason = AccountMergeService.can_merge_oauth_to_user(
                user_id,
                provider_name,
                provider_user_id
            )
            
            if not can_merge:
                return False, reason
            
            with get_db_session() as session:
                user = session.query(User).filter_by(id=user_id).first()
                if not user:
                    return False, "User not found"
                
                # Check if user email needs updating
                if provider_email and user.email != provider_email.lower():
                    logger.info(f"Merging user {user_id}: updating email from {user.email} to {provider_email}")
                    user.email = provider_email.lower()
                
                # Update user profile if missing data
                if provider_name_str and not user.full_name:
                    user.full_name = provider_name_str
                    user.display_name = provider_name_str
                
                # Create or update OAuth account
                oauth_account = session.query(OAuthAccount).filter_by(
                    user_id=user_id,
                    provider=provider_name
                ).first()
                
                if oauth_account:
                    # Update existing
                    oauth_account.provider_email = provider_email
                    oauth_account.provider_name = provider_name_str
                    oauth_account.provider_picture_url = provider_picture_url
                    if provider_metadata:
                        oauth_account.provider_metadata = provider_metadata
                    logger.info(f"Updated OAuth account {provider_name} for user {user_id}")
                else:
                    # Create new
                    oauth_account = OAuthAccount(
                        user_id=user_id,
                        provider=provider_name,
                        provider_user_id=provider_user_id,
                        provider_email=provider_email,
                        provider_name=provider_name_str,
                        provider_picture_url=provider_picture_url,
                        provider_metadata=provider_metadata
                    )
                    session.add(oauth_account)
                    logger.info(f"Created OAuth account link {provider_name} for user {user_id}")
                
                session.commit()
                
                return True, f"Successfully merged {provider_name} account"
        
        except Exception as e:
            logger.error(f"Error merging OAuth account: {e}", exc_info=True)
            return False, "An error occurred while merging account"
    
    @staticmethod
    def suggest_account_merge(
        oauth_provider: str,
        provider_email: Optional[str]
    ) -> Optional[User]:
        """
        Suggest an existing user to merge with based on email.
        
        Args:
            oauth_provider: OAuth provider name
            provider_email: Email from OAuth provider
            
        Returns:
            User to merge with, or None if no match
        """
        if not provider_email:
            return None
        
        try:
            with get_db_session() as session:
                # Find user with matching email
                user = session.query(User).filter_by(
                    email=provider_email.lower()
                ).first()
                
                if user:
                    # Check if this OAuth is already linked
                    existing_oauth = session.query(OAuthAccount).filter_by(
                        user_id=user.id,
                        provider=oauth_provider
                    ).first()
                    
                    if not existing_oauth:
                        logger.info(f"Found existing user {user.id} for {oauth_provider} merge suggestion")
                        return user
        
        except Exception as e:
            logger.error(f"Error suggesting account merge: {e}", exc_info=True)
        
        return None
    
    @staticmethod
    def get_merge_candidates(user_id: str) -> list:
        """
        Get list of potential OAuth accounts that could be merged with user's existing accounts.
        
        Args:
            user_id: User ID
            
        Returns:
            List of potential merge candidates with provider and email info
        """
        try:
            with get_db_session() as session:
                user = session.query(User).filter_by(id=user_id).first()
                if not user:
                    return []
                
                # Find all OAuth accounts with same email but linked to different users
                candidates = session.query(OAuthAccount).filter(
                    OAuthAccount.provider_email == user.email,
                    OAuthAccount.user_id != user_id
                ).all()
                
                return [
                    {
                        'provider': c.provider,
                        'email': c.provider_email,
                        'linked_user_id': c.user_id,
                        'linked_at': c.created_at.isoformat() if c.created_at else None
                    }
                    for c in candidates
                ]
        
        except Exception as e:
            logger.error(f"Error getting merge candidates: {e}", exc_info=True)
            return []
