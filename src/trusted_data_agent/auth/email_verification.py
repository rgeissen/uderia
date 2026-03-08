"""
Email verification service for OAuth and user signups.

Handles email verification workflows, token generation, and verification logic.
"""

import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import EmailVerificationToken, User

logger = logging.getLogger("quart.app")


class EmailVerificationService:
    """Service for managing email verification workflows."""
    
    # Token validity duration (24 hours)
    TOKEN_VALIDITY_HOURS = 24
    
    @staticmethod
    def generate_verification_token(
        user_id: str,
        email: str,
        verification_type: str = 'oauth',
        oauth_provider: Optional[str] = None
    ) -> str:
        """
        Generate an email verification token.
        
        Args:
            user_id: User ID to verify
            email: Email address to verify
            verification_type: Type of verification ('oauth', 'signup', 'email_change')
            oauth_provider: OAuth provider name if verification_type is 'oauth'
            
        Returns:
            Verification token string (raw, before hashing)
        """
        try:
            # Generate token
            token = secrets.token_urlsafe(32)
            token_hash = EmailVerificationService._hash_token(token)
            
            # Create expiry datetime
            expiry = datetime.now(timezone.utc) + timedelta(hours=EmailVerificationService.TOKEN_VALIDITY_HOURS)
            
            # Store token in database
            with get_db_session() as session:
                verification_token = EmailVerificationToken(
                    user_id=user_id,
                    token_hash=token_hash,
                    email=email,
                    verification_type=verification_type,
                    oauth_provider=oauth_provider,
                    expires_at=expiry
                )
                session.add(verification_token)
                session.commit()
            
            logger.info(f"Generated {verification_type} verification token for user {user_id}, email {email}")
            return token
        
        except Exception as e:
            logger.error(f"Error generating verification token: {e}", exc_info=True)
            raise
    
    @staticmethod
    def verify_email(token: str, email: str) -> Tuple[bool, Optional[str]]:
        """
        Verify an email using a verification token.
        
        Args:
            token: Raw verification token
            email: Email address being verified (for validation)
            
        Returns:
            Tuple of (success: bool, user_id: Optional[str])
        """
        try:
            token_hash = EmailVerificationService._hash_token(token)
            logger.debug(f"Verifying email {email} with token hash {token_hash}")
            
            with get_db_session() as session:
                # Find verification token
                verification_token = session.query(EmailVerificationToken).filter_by(
                    token_hash=token_hash
                ).first()
                
                if not verification_token:
                    logger.warning(f"Verification token not found for hash: {token_hash}")
                    logger.warning(f"Available token hashes in DB: {[t.token_hash[:16] for t in session.query(EmailVerificationToken).all()]}")
                    return False, None
                
                logger.debug(f"Found verification token for user {verification_token.user_id}, email {verification_token.email}")
                
                # Check if token is still valid
                if not verification_token.is_valid():
                    logger.warning(f"Verification token expired for user {verification_token.user_id}")
                    return False, None
                
                # Check if email matches
                if verification_token.email.lower() != email.lower():
                    logger.warning(f"Email mismatch in verification: {verification_token.email} != {email}")
                    return False, None
                
                # Mark as verified
                verification_token.verified_at = datetime.now(timezone.utc)
                
                # Update user email if needed
                user = session.query(User).filter_by(id=verification_token.user_id).first()
                if user and user.email != email:
                    user.email = email
                    logger.info(f"Updated user {user.id} email to {email}")
                
                session.commit()
                
                logger.info(f"Successfully verified email {email} for user {verification_token.user_id}")
                return True, verification_token.user_id
        
        except Exception as e:
            logger.error(f"Error verifying email: {e}", exc_info=True)
            return False, None
    
    @staticmethod
    def get_pending_verification(user_id: str) -> Optional[EmailVerificationToken]:
        """
        Get pending email verification token for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            EmailVerificationToken if pending, None otherwise
        """
        try:
            with get_db_session() as session:
                token = session.query(EmailVerificationToken).filter_by(
                    user_id=user_id
                ).filter(EmailVerificationToken.verified_at.is_(None)).first()
                
                if token and token.is_valid():
                    return token
                
                return None
        
        except Exception as e:
            logger.error(f"Error getting pending verification: {e}", exc_info=True)
            return None
    
    @staticmethod
    def is_email_verified(user_id: str, email: str) -> bool:
        """
        Check if an email has been verified for a user.
        
        Args:
            user_id: User ID
            email: Email address to check
            
        Returns:
            True if email is verified, False otherwise
        """
        try:
            with get_db_session() as session:
                token = session.query(EmailVerificationToken).filter_by(
                    user_id=user_id,
                    email=email.lower()
                ).first()
                
                return token is not None and token.is_verified()
        
        except Exception as e:
            logger.error(f"Error checking email verification: {e}", exc_info=True)
            return False
    
    @staticmethod
    def clean_expired_tokens():
        """Delete expired verification tokens."""
        try:
            with get_db_session() as session:
                now = datetime.now(timezone.utc)
                deleted = session.query(EmailVerificationToken).filter(
                    EmailVerificationToken.expires_at < now
                ).delete()
                session.commit()
                
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} expired email verification tokens")
        
        except Exception as e:
            logger.error(f"Error cleaning expired tokens: {e}", exc_info=True)
    
    @staticmethod
    def _hash_token(token: str) -> str:
        """Hash a verification token for storage."""
        import hashlib
        return hashlib.sha256(token.encode()).hexdigest()


class EmailVerificationValidator:
    """Validates email addresses and accounts for OAuth signups."""
    
    # Domains to exclude for email verification
    THROWAWAY_DOMAIN_PATTERNS = [
        'tempmail.', 'temp-mail.', '10minutemail.', 'guerrillamail.',
        'mailinator.', 'maildrop.', 'yopmail.', 'mytrashmail.'
    ]
    
    @staticmethod
    def is_valid_email_domain(email: str) -> bool:
        """
        Validate that email domain is not a known throwaway email service.
        
        Args:
            email: Email address
            
        Returns:
            True if domain is valid, False if throwaway
        """
        domain = email.lower().split('@')[1] if '@' in email else ''
        
        for pattern in EmailVerificationValidator.THROWAWAY_DOMAIN_PATTERNS:
            if pattern in domain:
                logger.warning(f"Throwaway email domain detected: {domain}")
                return False
        
        return True
    
    @staticmethod
    def should_verify_email(oauth_provider: str, is_email_verified: bool) -> bool:
        """
        Determine if email verification is required for OAuth signup.
        
        Args:
            oauth_provider: OAuth provider name
            is_email_verified: Whether provider verified the email
            
        Returns:
            True if verification should be required, False otherwise
        """
        # Providers that verify email themselves
        VERIFIED_PROVIDERS = ['google', 'microsoft']
        
        # Skip verification for providers that already verified email
        if oauth_provider in VERIFIED_PROVIDERS and is_email_verified:
            return False
        
        # Require verification for other providers
        return True
