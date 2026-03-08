"""
Credential encryption utilities for per-user credential storage.

Provides encryption/decryption of user credentials (API keys) using Fernet symmetric encryption.
Each user's credentials are encrypted with a key derived from a master secret and their user_id.
"""

import os
import json
import logging
import hashlib
import base64
from typing import Optional, Dict, Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import UserCredential

logger = logging.getLogger("quart.app")

# Master encryption key from environment
# In production, this should be a secure 256-bit key
MASTER_ENCRYPTION_KEY = os.environ.get('TDA_ENCRYPTION_KEY', 'dev-master-key-change-in-production')

# Warn if using default key
if MASTER_ENCRYPTION_KEY == 'dev-master-key-change-in-production':
    if os.environ.get('TDA_ENV') == 'production':
        logger.error("SECURITY WARNING: Using default encryption key! Set TDA_ENCRYPTION_KEY environment variable!")
    else:
        logger.warning("Using default encryption key (development mode)")


def _derive_user_key(user_id: str) -> bytes:
    """
    Derive a user-specific encryption key from master key and user_id.
    
    Uses PBKDF2 key derivation with user_id as salt.
    
    Args:
        user_id: User's unique identifier
        
    Returns:
        32-byte encryption key
    """
    # Use user_id as salt (converted to bytes)
    salt = user_id.encode('utf-8')
    
    # Derive key using PBKDF2HMAC
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,  # NIST recommendation
    )
    
    key = kdf.derive(MASTER_ENCRYPTION_KEY.encode('utf-8'))
    
    # Fernet requires base64-encoded key
    return base64.urlsafe_b64encode(key)


def encrypt_credentials(user_id: str, provider: str, credentials: Dict[str, Any]) -> bool:
    """
    Encrypt and store user credentials for a specific provider.
    
    Args:
        user_id: User's unique identifier
        provider: Provider name (Amazon, Google, OpenAI, etc.)
        credentials: Dictionary of credential key-value pairs
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Derive user-specific key
        key = _derive_user_key(user_id)
        fernet = Fernet(key)
        
        # Serialize credentials to JSON
        credentials_json = json.dumps(credentials)
        
        # Encrypt
        encrypted_data = fernet.encrypt(credentials_json.encode('utf-8'))
        encrypted_str = encrypted_data.decode('utf-8')
        
        # Store in database
        with get_db_session() as session:
            # Check if credential already exists
            existing = session.query(UserCredential).filter_by(
                user_id=user_id,
                provider=provider
            ).first()
            
            if existing:
                # Update existing
                existing.credentials_encrypted = encrypted_str
                logger.info(f"Updated encrypted credentials for user {user_id}, provider {provider}")
            else:
                # Create new
                credential = UserCredential(
                    user_id=user_id,
                    provider=provider,
                    credentials_encrypted=encrypted_str
                )
                session.add(credential)
                logger.info(f"Stored encrypted credentials for user {user_id}, provider {provider}")
        
        return True
    
    except Exception as e:
        logger.error(f"Failed to encrypt credentials for user {user_id}, provider {provider}: {e}", exc_info=True)
        return False


def decrypt_credentials(user_id: str, provider: str) -> Optional[Dict[str, Any]]:
    """
    Decrypt and retrieve user credentials for a specific provider.
    
    Args:
        user_id: User's unique identifier
        provider: Provider name (Amazon, Google, OpenAI, etc.)
        
    Returns:
        Dictionary of decrypted credentials, or None if not found/error
    """
    try:
        # Retrieve from database
        with get_db_session() as session:
            credential = session.query(UserCredential).filter_by(
                user_id=user_id,
                provider=provider
            ).first()
            
            if not credential:
                logger.debug(f"No credentials found for user {user_id}, provider {provider}")
                return None
            
            encrypted_str = credential.credentials_encrypted
        
        # Derive user-specific key
        key = _derive_user_key(user_id)
        fernet = Fernet(key)
        
        # Decrypt
        encrypted_data = encrypted_str.encode('utf-8')
        decrypted_json = fernet.decrypt(encrypted_data).decode('utf-8')
        
        # Deserialize
        credentials = json.loads(decrypted_json)
        
        logger.debug(f"Successfully decrypted credentials for user {user_id}, provider {provider}")
        return credentials
    
    except InvalidToken:
        logger.error(f"Invalid encryption token for user {user_id}, provider {provider} - credentials may be corrupted")
        return None
    except Exception as e:
        logger.error(f"Failed to decrypt credentials for user {user_id}, provider {provider}: {e}", exc_info=True)
        return None


def delete_credentials(user_id: str, provider: str) -> bool:
    """
    Delete stored credentials for a user and provider.
    
    Args:
        user_id: User's unique identifier
        provider: Provider name
        
    Returns:
        True if deleted, False otherwise
    """
    try:
        with get_db_session() as session:
            result = session.query(UserCredential).filter_by(
                user_id=user_id,
                provider=provider
            ).delete()
            
            if result > 0:
                logger.info(f"Deleted credentials for user {user_id}, provider {provider}")
                return True
            else:
                logger.warning(f"No credentials found to delete for user {user_id}, provider {provider}")
                return False
    
    except Exception as e:
        logger.error(f"Failed to delete credentials for user {user_id}, provider {provider}: {e}", exc_info=True)
        return False


def delete_all_user_credentials(user_id: str) -> int:
    """
    Delete all stored credentials for a user (e.g., on account deletion).
    
    Args:
        user_id: User's unique identifier
        
    Returns:
        Number of credential records deleted
    """
    try:
        with get_db_session() as session:
            result = session.query(UserCredential).filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {result} credential record(s) for user {user_id}")
            return result
    
    except Exception as e:
        logger.error(f"Failed to delete credentials for user {user_id}: {e}", exc_info=True)
        return 0


def list_user_providers(user_id: str) -> list[str]:
    """
    List all providers that have stored credentials for a user.
    
    Args:
        user_id: User's unique identifier
        
    Returns:
        List of provider names
    """
    try:
        with get_db_session() as session:
            credentials = session.query(UserCredential.provider).filter_by(user_id=user_id).all()
            return [c.provider for c in credentials]
    
    except Exception as e:
        logger.error(f"Failed to list providers for user {user_id}: {e}", exc_info=True)
        return []


def rotate_encryption_key(old_key: str, new_key: str) -> tuple[int, int]:
    """
    Rotate encryption key for all stored credentials.
    
    WARNING: This is a sensitive operation. Backup database before running.
    
    Args:
        old_key: Old master encryption key
        new_key: New master encryption key
        
    Returns:
        Tuple of (successful_count, failed_count)
    """
    global MASTER_ENCRYPTION_KEY
    
    successful = 0
    failed = 0
    
    try:
        with get_db_session() as session:
            all_credentials = session.query(UserCredential).all()
            
            logger.info(f"Starting key rotation for {len(all_credentials)} credential records")
            
            for cred in all_credentials:
                try:
                    # Decrypt with old key
                    old_master = MASTER_ENCRYPTION_KEY
                    MASTER_ENCRYPTION_KEY = old_key
                    
                    decrypted = decrypt_credentials(cred.user_id, cred.provider)
                    
                    if decrypted:
                        # Re-encrypt with new key
                        MASTER_ENCRYPTION_KEY = new_key
                        
                        if encrypt_credentials(cred.user_id, cred.provider, decrypted):
                            successful += 1
                        else:
                            failed += 1
                            logger.error(f"Failed to re-encrypt credentials for user {cred.user_id}, provider {cred.provider}")
                    else:
                        failed += 1
                        logger.error(f"Failed to decrypt credentials for user {cred.user_id}, provider {cred.provider}")
                    
                    # Restore original key for next iteration
                    MASTER_ENCRYPTION_KEY = old_master
                
                except Exception as e:
                    failed += 1
                    logger.error(f"Error rotating key for user {cred.user_id}, provider {cred.provider}: {e}")
            
            logger.info(f"Key rotation complete: {successful} successful, {failed} failed")
            return successful, failed
    
    except Exception as e:
        logger.error(f"Key rotation failed: {e}", exc_info=True)
        return successful, failed
