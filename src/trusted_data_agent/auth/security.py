"""
Security utilities for authentication.

Provides password hashing, JWT token generation/validation, and related security functions.
"""

import os
import logging
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

import bcrypt
import jwt

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import AuthToken, User

logger = logging.getLogger("quart.app")


def _get_or_create_jwt_secret() -> str:
    """
    Get JWT secret key from environment, or load/create persistent key file.
    
    Priority:
    1. TDA_JWT_SECRET_KEY environment variable
    2. tda_keys/jwt_secret.key file
    3. Generate new key and save to file
    
    Returns:
        JWT secret key string
    """
    # Check environment variable first
    env_key = os.environ.get('TDA_JWT_SECRET_KEY')
    if env_key:
        logger.info("Using JWT secret key from TDA_JWT_SECRET_KEY environment variable")
        return env_key
    
    # Use get_project_root to find the correct location
    from trusted_data_agent.core.utils import get_project_root
    project_root = get_project_root()
    key_dir = project_root / 'tda_keys'
    key_file = key_dir / 'jwt_secret.key'
    
    try:
        if key_file.exists():
            with open(key_file, 'r', encoding='utf-8') as f:
                stored_key = f.read().strip()
                if stored_key:
                    logger.info(f"Loaded JWT secret key from {key_file}")
                    return stored_key
        
        # Generate new key and save it
        new_key = secrets.token_urlsafe(32)
        key_dir.mkdir(parents=True, exist_ok=True)
        
        with open(key_file, 'w', encoding='utf-8') as f:
            f.write(new_key)
        
        # Set restrictive permissions (owner read/write only)
        key_file.chmod(0o600)
        
        logger.info(f"Generated new JWT secret key and saved to {key_file}")
        return new_key
        
    except Exception as e:
        logger.error(f"Error loading/creating JWT secret key file: {e}. Using temporary key.", exc_info=True)
        logger.warning("JWT tokens will not persist across restarts!")
        return secrets.token_urlsafe(32)


# Configuration from environment or persistent storage
JWT_SECRET_KEY = _get_or_create_jwt_secret()
JWT_ALGORITHM = 'HS256'
JWT_EXPIRY_HOURS = int(os.environ.get('TDA_JWT_EXPIRY_HOURS', '24'))
PASSWORD_MIN_LENGTH = int(os.environ.get('TDA_PASSWORD_MIN_LENGTH', '8'))
MAX_LOGIN_ATTEMPTS = int(os.environ.get('TDA_MAX_LOGIN_ATTEMPTS', '5'))
LOCKOUT_DURATION_MINUTES = int(os.environ.get('TDA_LOCKOUT_DURATION_MINUTES', '15'))


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt with salt.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password string
    """
    if not password:
        raise ValueError("Password cannot be empty")
    
    # Generate salt and hash password
    salt = bcrypt.gensalt(rounds=12)
    password_hash = bcrypt.hashpw(password.encode('utf-8'), salt)
    
    return password_hash.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against its hash using constant-time comparison.
    
    Args:
        password: Plain text password to verify
        password_hash: Stored password hash
        
    Returns:
        True if password matches, False otherwise
    """
    if not password or not password_hash:
        return False
    
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False


def generate_auth_token(
    user_id: str,
    username: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> tuple[str, datetime]:
    """
    Generate a JWT authentication token for a user.
    
    Args:
        user_id: User's unique identifier
        username: User's username
        ip_address: Optional IP address of the request
        user_agent: Optional user agent string
        
    Returns:
        Tuple of (token_string, expiry_datetime)
    """
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(hours=JWT_EXPIRY_HOURS)
    
    # Generate unique token ID
    jti = secrets.token_urlsafe(32)
    
    # Create JWT payload
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': expiry,
        'iat': now,
        'jti': jti
    }
    
    # Generate JWT token
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    # Store token hash in database for tracking/revocation
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    try:
        with get_db_session() as session:
            auth_token = AuthToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expiry,
                ip_address=ip_address,
                user_agent=user_agent
            )
            session.add(auth_token)
    except Exception as e:
        logger.error(f"Failed to store auth token: {e}")
        # Continue anyway - token is still valid even if storage fails
    
    return token, expiry


def verify_auth_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT authentication token.
    
    Args:
        token: JWT token string
        
    Returns:
        Dictionary with user_id, username if valid, None otherwise
    """
    if not token:
        return None
    
    try:
        # Decode and verify JWT
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Check if token is revoked in database
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        with get_db_session() as session:
            auth_token = session.query(AuthToken).filter_by(token_hash=token_hash).first()
            
            if auth_token and auth_token.revoked:
                logger.warning(f"Attempt to use revoked token for user {payload.get('user_id')}")
                return None
        
        return {
            'user_id': payload['user_id'],
            'username': payload['username'],
            'exp': payload['exp'],
            'iat': payload['iat'],
            'jti': payload['jti']
        }
    
    except jwt.ExpiredSignatureError:
        logger.info("Expired token presented")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        return None
    except Exception as e:
        logger.error(f"Error verifying token: {e}", exc_info=True)
        return None


def create_internal_token(user_uuid: str, username: str = "internal") -> str:
    """
    Create a short-lived internal JWT token for internal service-to-service calls.

    This is used by the Genie coordinator to make authenticated REST API calls
    to create slave sessions and execute queries. The token is short-lived (5 minutes)
    and not stored in the database to avoid clutter.

    Args:
        user_uuid: User's unique identifier
        username: Username (defaults to "internal")

    Returns:
        JWT token string
    """
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=30)  # Extended for Genie coordination (slave queries can take time)

    # Generate unique token ID
    jti = secrets.token_urlsafe(16)

    # Create JWT payload
    payload = {
        'user_id': user_uuid,
        'username': username,
        'exp': expiry,
        'iat': now,
        'jti': jti,
        'internal': True  # Mark as internal token
    }

    # Generate JWT token (not stored in database)
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    return token


def revoke_token(token: str) -> bool:
    """
    Revoke an authentication token.
    
    Args:
        token: JWT token string to revoke
        
    Returns:
        True if revoked successfully, False otherwise
    """
    try:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        with get_db_session() as session:
            auth_token = session.query(AuthToken).filter_by(token_hash=token_hash).first()
            
            if auth_token:
                auth_token.revoked = True
                auth_token.revoked_at = datetime.now(timezone.utc)
                logger.info(f"Token revoked for user {auth_token.user_id}")
                return True
            else:
                logger.warning("Attempted to revoke non-existent token")
                return False
    
    except Exception as e:
        logger.error(f"Error revoking token: {e}", exc_info=True)
        return False


def revoke_all_user_tokens(user_id: str) -> int:
    """
    Revoke all active tokens for a user (e.g., on password change).
    
    Args:
        user_id: User's unique identifier
        
    Returns:
        Number of tokens revoked
    """
    try:
        with get_db_session() as session:
            now = datetime.now(timezone.utc)
            
            tokens = session.query(AuthToken).filter(
                AuthToken.user_id == user_id,
                AuthToken.revoked == False,
                AuthToken.expires_at > now
            ).all()
            
            count = len(tokens)
            for token in tokens:
                token.revoked = True
                token.revoked_at = now
            
            logger.info(f"Revoked {count} tokens for user {user_id}")
            return count
    
    except Exception as e:
        logger.error(f"Error revoking user tokens: {e}", exc_info=True)
        return 0


def cleanup_expired_tokens() -> int:
    """
    Remove expired tokens from database (scheduled maintenance task).
    
    Returns:
        Number of tokens cleaned up
    """
    try:
        with get_db_session() as session:
            now = datetime.now(timezone.utc)
            
            # Delete tokens expired more than 7 days ago
            cutoff = now - timedelta(days=7)
            
            result = session.query(AuthToken).filter(
                AuthToken.expires_at < cutoff
            ).delete()
            
            logger.info(f"Cleaned up {result} expired tokens")
            return result
    
    except Exception as e:
        logger.error(f"Error cleaning up tokens: {e}", exc_info=True)
        return 0


def check_user_lockout(user: User) -> tuple[bool, Optional[datetime]]:
    """
    Check if a user account is locked due to failed login attempts.
    
    Args:
        user: User object to check
        
    Returns:
        Tuple of (is_locked, locked_until)
    """
    if not user.locked_until:
        return False, None
    
    now = datetime.now(timezone.utc)
    
    # Handle both timezone-aware and naive datetimes
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        # Make naive datetime aware (assume UTC)
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    
    if locked_until > now:
        return True, user.locked_until
    
    # Lockout expired, clear it
    return False, None


def record_failed_login(user: User) -> None:
    """
    Record a failed login attempt and potentially lock the account.
    
    Args:
        user: User object
    """
    try:
        with get_db_session() as session:
            # Re-query to get fresh object in this session
            db_user = session.query(User).filter_by(id=user.id).first()
            if not db_user:
                return
            
            db_user.failed_login_attempts += 1
            
            # Lock account if threshold exceeded
            if db_user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                db_user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                logger.warning(f"User {db_user.username} locked due to {db_user.failed_login_attempts} failed login attempts")
            
    except Exception as e:
        logger.error(f"Error recording failed login: {e}", exc_info=True)


def reset_failed_login_attempts(user: User) -> None:
    """
    Reset failed login attempts counter on successful login.
    
    Args:
        user: User object
    """
    try:
        with get_db_session() as session:
            db_user = session.query(User).filter_by(id=user.id).first()
            if not db_user:
                return
            
            db_user.failed_login_attempts = 0
            db_user.locked_until = None
            db_user.last_login_at = datetime.now(timezone.utc)
    
    except Exception as e:
        logger.error(f"Error resetting failed login attempts: {e}", exc_info=True)


def validate_password_strength(password: str) -> tuple[bool, list[str]]:
    """
    Validate password meets minimum strength requirements.
    
    Args:
        password: Password to validate
        
    Returns:
        Tuple of (is_valid, [error_messages])
    """
    errors = []
    
    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long")
    
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")
    
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")
    
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one number")
    
    # Optional: special character requirement
    # if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
    #     errors.append("Password must contain at least one special character")
    
    return len(errors) == 0, errors


# ============================================================================
# Access Token Management
# ============================================================================

def generate_access_token(name: str = "API Token") -> str:
    """
    Generate a new access token with format: tda_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    
    Args:
        name: User-friendly name for the token
        
    Returns:
        Full access token string (40 chars: prefix + 32 random chars)
    """
    # Generate cryptographically secure random token
    random_part = secrets.token_urlsafe(24)  # ~32 chars in base64
    token = f"tda_{random_part}"
    return token


def hash_access_token(token: str) -> str:
    """
    Hash an access token for secure storage.
    
    Args:
        token: Full access token string
        
    Returns:
        SHA256 hash of the token
    """
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def get_token_prefix(token: str) -> str:
    """
    Extract displayable prefix from access token.
    
    Args:
        token: Full access token (e.g., tda_abc123...)
        
    Returns:
        First 12 characters for display (e.g., "tda_abc12...")
    """
    return token[:12] if len(token) >= 12 else token


def verify_access_token(token: str) -> Optional[User]:
    """
    Verify an access token and return the associated user.
    
    Args:
        token: Full access token string
        
    Returns:
        User object if token is valid, None otherwise
    """
    from trusted_data_agent.auth.models import AccessToken
    
    if not token or not token.startswith('tda_'):
        return None
    
    token_hash = hash_access_token(token)
    
    try:
        with get_db_session() as session:
            # Find token by hash
            access_token = session.query(AccessToken).filter_by(
                token_hash=token_hash,
                revoked=False
            ).first()
            
            if not access_token:
                return None
            
            # Check if token is valid (not expired)
            if not access_token.is_valid():
                return None
            
            # Get associated user
            user = session.query(User).filter_by(
                id=access_token.user_id,
                is_active=True
            ).first()
            
            if not user:
                return None
            
            # Update last used timestamp BEFORE loading user attributes
            access_token.last_used_at = datetime.now(timezone.utc)
            access_token.use_count += 1
            session.commit()
            
            # Now load all user attributes AFTER commit (so they don't get expired)
            # Access each attribute to force SQLAlchemy to load it into the instance
            _ = user.id
            _ = user.username
            _ = user.id
            _ = user.email
            _ = user.display_name
            _ = user.is_admin
            _ = user.is_active
            _ = user.created_at
            _ = user.last_login_at
            
            # Detach from session
            session.expunge(user)
            return user
            
    except Exception as e:
        logger.error(f"Error verifying access token: {e}", exc_info=True)
        return None


def create_access_token(user_id: str, name: str, expires_in_days: Optional[int] = None) -> tuple[str, str]:
    """
    Create and store a new access token for a user.
    
    Args:
        user_id: User ID to associate with the token
        name: User-friendly name for the token
        expires_in_days: Optional expiration in days (None = never expires)
        
    Returns:
        Tuple of (token_id, full_token) - token is only returned once!
    """
    from trusted_data_agent.auth.models import AccessToken
    
    # Generate new token
    token = generate_access_token(name)
    token_hash = hash_access_token(token)
    token_prefix = get_token_prefix(token)
    
    # Calculate expiration
    expires_at = None
    if expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    
    try:
        with get_db_session() as session:
            # Create token record
            access_token = AccessToken(
                user_id=user_id,
                token_prefix=token_prefix,
                token_hash=token_hash,
                name=name,
                expires_at=expires_at
            )
            
            session.add(access_token)
            session.commit()
            
            token_id = access_token.id
            
        logger.info(f"Created access token '{name}' (ID: {token_id}) for user {user_id}")
        return token_id, token
        
    except Exception as e:
        logger.error(f"Error creating access token: {e}", exc_info=True)
        raise


def revoke_access_token(token_id: str, user_id: str) -> bool:
    """
    Revoke an access token.
    
    Args:
        token_id: Token ID to revoke
        user_id: User ID (for authorization check)
        
    Returns:
        True if revoked successfully, False otherwise
    """
    from trusted_data_agent.auth.models import AccessToken
    
    try:
        with get_db_session() as session:
            access_token = session.query(AccessToken).filter_by(
                id=token_id,
                user_id=user_id
            ).first()
            
            if not access_token:
                return False
            
            access_token.revoked = True
            access_token.revoked_at = datetime.now(timezone.utc)
            session.commit()
            
        logger.info(f"Revoked access token {token_id} for user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error revoking access token: {e}", exc_info=True)
        return False


def list_access_tokens(user_id: str, include_revoked: bool = False) -> list:
    """
    List all access tokens for a user.
    
    Args:
        user_id: User ID
        include_revoked: Whether to include revoked tokens
        
    Returns:
        List of token dictionaries
    """
    from trusted_data_agent.auth.models import AccessToken
    
    try:
        with get_db_session() as session:
            query = session.query(AccessToken).filter_by(user_id=user_id)
            
            if not include_revoked:
                query = query.filter_by(revoked=False)
            
            tokens = query.order_by(AccessToken.created_at.desc()).all()
            
            return [token.to_dict() for token in tokens]
            
    except Exception as e:
        logger.error(f"Error listing access tokens: {e}", exc_info=True)
        return []
