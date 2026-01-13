"""
Password reset service for forgot password functionality.

Handles password reset token generation, validation, and password updates.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, PasswordResetToken

logger = logging.getLogger("quart.app")

# Token validity period
TOKEN_VALIDITY_HOURS = 1  # Password reset tokens expire after 1 hour


class PasswordResetService:
    """Service for handling password reset operations."""

    @staticmethod
    def generate_reset_token(user_id: str, email: str) -> Optional[str]:
        """
        Generate a password reset token for a user.

        Args:
            user_id: The user's ID
            email: The user's email address

        Returns:
            The raw token (to be sent via email) or None if failed
        """
        try:
            # Generate cryptographically secure token
            raw_token = secrets.token_urlsafe(32)

            # Hash the token for storage (never store raw tokens)
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

            # Calculate expiry
            expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_VALIDITY_HOURS)

            with get_db_session() as session:
                # Invalidate any existing reset tokens for this user
                existing_tokens = session.query(PasswordResetToken).filter_by(
                    user_id=user_id,
                    used=False
                ).all()

                for token in existing_tokens:
                    token.used = True
                    token.used_at = datetime.now(timezone.utc)

                # Create new token
                reset_token = PasswordResetToken(
                    user_id=user_id,
                    token_hash=token_hash,
                    expires_at=expires_at
                )

                session.add(reset_token)
                session.commit()

                logger.info(f"Password reset token generated for user {user_id}")
                return raw_token

        except Exception as e:
            logger.error(f"Error generating password reset token: {e}", exc_info=True)
            return None

    @staticmethod
    def validate_reset_token(token: str, email: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate a password reset token.

        Args:
            token: The raw token from the reset link
            email: The email address from the reset link

        Returns:
            Tuple of (is_valid, user_id, error_message)
        """
        try:
            # Hash the provided token
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            with get_db_session() as session:
                # Find the token
                reset_token = session.query(PasswordResetToken).filter_by(
                    token_hash=token_hash
                ).first()

                if not reset_token:
                    return False, None, "Invalid or expired reset link"

                # Check if already used
                if reset_token.used:
                    return False, None, "This reset link has already been used"

                # Check if expired
                if not reset_token.is_valid():
                    return False, None, "This reset link has expired"

                # Verify the user exists and email matches
                user = session.query(User).filter_by(id=reset_token.user_id).first()

                if not user:
                    return False, None, "User not found"

                if user.email.lower() != email.lower():
                    return False, None, "Invalid reset link"

                return True, user.id, None

        except Exception as e:
            logger.error(f"Error validating password reset token: {e}", exc_info=True)
            return False, None, "Error validating reset link"

    @staticmethod
    def reset_password(token: str, email: str, new_password_hash: str) -> Tuple[bool, Optional[str]]:
        """
        Reset the user's password using a valid reset token.

        Args:
            token: The raw token from the reset link
            email: The email address from the reset link
            new_password_hash: The hashed new password

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Validate the token first
            is_valid, user_id, error_message = PasswordResetService.validate_reset_token(token, email)

            if not is_valid:
                return False, error_message

            # Hash the token to find it in database
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            with get_db_session() as session:
                # Get the token and user
                reset_token = session.query(PasswordResetToken).filter_by(
                    token_hash=token_hash
                ).first()

                user = session.query(User).filter_by(id=user_id).first()

                if not reset_token or not user:
                    return False, "Invalid reset link"

                # Update the password
                user.password_hash = new_password_hash
                user.updated_at = datetime.now(timezone.utc)

                # Mark the token as used
                reset_token.used = True
                reset_token.used_at = datetime.now(timezone.utc)

                session.commit()

                logger.info(f"Password reset successful for user {user_id}")
                return True, None

        except Exception as e:
            logger.error(f"Error resetting password: {e}", exc_info=True)
            return False, "Error resetting password"

    @staticmethod
    def clean_expired_tokens() -> int:
        """
        Remove expired password reset tokens from the database.

        Returns:
            Number of tokens deleted
        """
        try:
            with get_db_session() as session:
                now = datetime.now(timezone.utc)

                # Delete expired tokens
                deleted = session.query(PasswordResetToken).filter(
                    PasswordResetToken.expires_at < now
                ).delete()

                session.commit()

                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} expired password reset tokens")

                return deleted

        except Exception as e:
            logger.error(f"Error cleaning expired password reset tokens: {e}", exc_info=True)
            return 0
