"""
TTS (Text-to-Speech) credential management and client resolution service.

Manages three TTS modes:
- 'disabled': TTS is off
- 'global': All users use admin-provided global credentials
- 'user': Each user provides their own TTS credentials

Global credentials are stored encrypted in the tts_global_config table
(not in user_credentials, since that table has FK constraints to users.id).
Per-user credentials are stored in user_credentials with provider='GoogleTTS'.
"""

import os
import json
import logging
import base64
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import SystemSettings, TtsGlobalConfig
from trusted_data_agent.core.config import APP_CONFIG, APP_STATE

logger = logging.getLogger("quart.app")

# Sentinel salt for global TTS credential encryption key derivation
_GLOBAL_TTS_KEY_SALT = "GLOBAL_TTS"

# Master encryption key (same as auth/encryption.py)
_MASTER_KEY = os.environ.get('TDA_ENCRYPTION_KEY', 'dev-master-key-change-in-production')

VALID_TTS_MODES = ('disabled', 'global', 'user')


def _derive_global_key() -> bytes:
    """Derive encryption key for global TTS credentials using a fixed salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_GLOBAL_TTS_KEY_SALT.encode('utf-8'),
        iterations=100000,
    )
    key = kdf.derive(_MASTER_KEY.encode('utf-8'))
    return base64.urlsafe_b64encode(key)


# --- TTS Mode ---

def get_tts_mode() -> str:
    """Read tts_mode from system_settings. Returns 'disabled' if not found."""
    try:
        with get_db_session() as session:
            setting = session.query(SystemSettings).filter_by(setting_key='tts_mode').first()
            if setting and setting.setting_value in VALID_TTS_MODES:
                return setting.setting_value
    except Exception as e:
        logger.error(f"Error reading tts_mode: {e}")
    return 'disabled'


def set_tts_mode(mode: str) -> bool:
    """
    Update tts_mode in system_settings.
    Also syncs APP_CONFIG.VOICE_CONVERSATION_ENABLED and invalidates TTS caches.
    """
    if mode not in VALID_TTS_MODES:
        logger.error(f"Invalid TTS mode: {mode}")
        return False

    try:
        with get_db_session() as session:
            setting = session.query(SystemSettings).filter_by(setting_key='tts_mode').first()
            if setting:
                setting.setting_value = mode
            else:
                setting = SystemSettings(
                    setting_key='tts_mode',
                    setting_value=mode,
                    description='TTS credential mode: disabled, global, or user'
                )
                session.add(setting)
            session.commit()

        # Sync APP_CONFIG
        APP_CONFIG.VOICE_CONVERSATION_ENABLED = (mode != 'disabled')

        # Invalidate all cached TTS clients
        invalidate_tts_cache()

        logger.info(f"TTS mode set to: {mode} (voice_enabled={APP_CONFIG.VOICE_CONVERSATION_ENABLED})")
        return True

    except Exception as e:
        logger.error(f"Error setting tts_mode: {e}", exc_info=True)
        return False


# --- Global TTS Credentials ---

def save_global_tts_credentials(credentials_json_str: str) -> bool:
    """Encrypt and store global TTS credentials in tts_global_config table."""
    try:
        # Validate JSON before encrypting
        json.loads(credentials_json_str)

        key = _derive_global_key()
        fernet = Fernet(key)
        encrypted = fernet.encrypt(credentials_json_str.encode('utf-8')).decode('utf-8')

        with get_db_session() as session:
            existing = session.query(TtsGlobalConfig).filter_by(config_key='global_credentials').first()
            if existing:
                existing.config_value = encrypted
            else:
                entry = TtsGlobalConfig(
                    config_key='global_credentials',
                    config_value=encrypted
                )
                session.add(entry)
            session.commit()

        # Invalidate global TTS client cache
        invalidate_tts_cache()
        logger.info("Global TTS credentials saved successfully")
        return True

    except json.JSONDecodeError:
        logger.error("Global TTS credentials are not valid JSON")
        return False
    except Exception as e:
        logger.error(f"Error saving global TTS credentials: {e}", exc_info=True)
        return False


def get_global_tts_credentials() -> Optional[str]:
    """Decrypt and return global TTS credentials JSON string, or None."""
    try:
        with get_db_session() as session:
            entry = session.query(TtsGlobalConfig).filter_by(config_key='global_credentials').first()
            if not entry:
                return None
            encrypted_str = entry.config_value

        key = _derive_global_key()
        fernet = Fernet(key)
        decrypted = fernet.decrypt(encrypted_str.encode('utf-8')).decode('utf-8')
        return decrypted

    except InvalidToken:
        logger.error("Failed to decrypt global TTS credentials - may be corrupted")
        return None
    except Exception as e:
        logger.error(f"Error reading global TTS credentials: {e}", exc_info=True)
        return None


def delete_global_tts_credentials() -> bool:
    """Delete global TTS credentials."""
    try:
        with get_db_session() as session:
            result = session.query(TtsGlobalConfig).filter_by(config_key='global_credentials').delete()
            session.commit()
            if result > 0:
                invalidate_tts_cache()
                logger.info("Global TTS credentials deleted")
            return True
    except Exception as e:
        logger.error(f"Error deleting global TTS credentials: {e}", exc_info=True)
        return False


def has_global_tts_credentials() -> bool:
    """Check if global TTS credentials exist (without decrypting)."""
    try:
        with get_db_session() as session:
            entry = session.query(TtsGlobalConfig).filter_by(config_key='global_credentials').first()
            return entry is not None
    except Exception:
        return False


def get_global_credentials_project_id() -> Optional[str]:
    """Extract project_id from global credentials for display purposes."""
    creds_json = get_global_tts_credentials()
    if creds_json:
        try:
            creds = json.loads(creds_json)
            return creds.get('project_id')
        except Exception:
            pass
    return None


# --- Per-User TTS Credentials ---

def save_user_tts_credentials(user_id: str, credentials_json_str: str) -> bool:
    """Encrypt and store per-user TTS credentials via the existing credential system."""
    try:
        json.loads(credentials_json_str)  # Validate JSON
        from trusted_data_agent.auth.encryption import encrypt_credentials
        result = encrypt_credentials(user_id, 'GoogleTTS', {'credentials_json': credentials_json_str})
        if result:
            invalidate_tts_cache(user_id=user_id)
            logger.info(f"User TTS credentials saved for user {user_id}")
        return result
    except json.JSONDecodeError:
        logger.error(f"User TTS credentials are not valid JSON for user {user_id}")
        return False
    except Exception as e:
        logger.error(f"Error saving user TTS credentials: {e}", exc_info=True)
        return False


def get_user_tts_credentials(user_id: str) -> Optional[str]:
    """Decrypt and return per-user TTS credentials JSON string, or None."""
    try:
        from trusted_data_agent.auth.encryption import decrypt_credentials
        creds = decrypt_credentials(user_id, 'GoogleTTS')
        if creds:
            return creds.get('credentials_json')
        return None
    except Exception as e:
        logger.error(f"Error reading user TTS credentials: {e}", exc_info=True)
        return None


def delete_user_tts_credentials(user_id: str) -> bool:
    """Delete per-user TTS credentials."""
    try:
        from trusted_data_agent.auth.encryption import delete_credentials
        result = delete_credentials(user_id, 'GoogleTTS')
        if result:
            invalidate_tts_cache(user_id=user_id)
        return result
    except Exception as e:
        logger.error(f"Error deleting user TTS credentials: {e}", exc_info=True)
        return False


def has_user_tts_credentials(user_id: str) -> bool:
    """Check if user has TTS credentials stored."""
    try:
        from trusted_data_agent.auth.encryption import decrypt_credentials
        creds = decrypt_credentials(user_id, 'GoogleTTS')
        return creds is not None and 'credentials_json' in creds
    except Exception:
        return False


# --- TTS Client Resolution ---

def resolve_tts_client(user_id: str):
    """
    Resolve the TTS client based on the current tts_mode and user context.

    Returns a TextToSpeechClient or None.
    - disabled mode: returns None
    - global mode: returns cached global client (DB creds -> env var fallback)
    - user mode: returns cached per-user client
    """
    from trusted_data_agent.core.utils import get_tts_client

    mode = get_tts_mode()

    if mode == 'disabled':
        return None

    if mode == 'global':
        # Check cache
        cached = APP_STATE.get('tts_client_global')
        if cached is not None:
            return cached

        # Try global credentials from DB
        creds_json = get_global_tts_credentials()
        if creds_json:
            client = get_tts_client(credentials_json=creds_json)
            if client:
                APP_STATE['tts_client_global'] = client
                return client

        # Fallback to env var
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            client = get_tts_client()
            if client:
                APP_STATE['tts_client_global'] = client
                return client

        logger.warning("Global TTS mode active but no credentials available")
        return None

    if mode == 'user':
        # Check per-user cache
        user_clients = APP_STATE.get('tts_clients_by_user', {})
        cached = user_clients.get(user_id)
        if cached is not None:
            return cached

        # Try user credentials from DB
        creds_json = get_user_tts_credentials(user_id)
        if creds_json:
            client = get_tts_client(credentials_json=creds_json)
            if client:
                if 'tts_clients_by_user' not in APP_STATE:
                    APP_STATE['tts_clients_by_user'] = {}
                APP_STATE['tts_clients_by_user'][user_id] = client
                return client

        logger.info(f"User TTS mode active but no credentials for user {user_id}")
        return None

    return None


def invalidate_tts_cache(user_id: str = None):
    """
    Invalidate cached TTS clients.
    If user_id is None, invalidate all caches (global + all users).
    If user_id is provided, invalidate only that user's cache.
    """
    if user_id is None:
        APP_STATE['tts_client_global'] = None
        APP_STATE['tts_clients_by_user'] = {}
        logger.info("All TTS client caches invalidated")
    else:
        user_clients = APP_STATE.get('tts_clients_by_user', {})
        if user_id in user_clients:
            del user_clients[user_id]
            logger.info(f"TTS client cache invalidated for user {user_id}")


def test_tts_credentials(credentials_json_str: str) -> dict:
    """
    Test TTS credentials by attempting to create a client.
    Returns {'success': bool, 'error': str or None}.
    """
    from trusted_data_agent.core.utils import get_tts_client

    try:
        json.loads(credentials_json_str)  # Validate JSON first
    except json.JSONDecodeError:
        return {'success': False, 'error': 'Invalid JSON format'}

    client = get_tts_client(credentials_json=credentials_json_str)
    if client:
        return {'success': True, 'error': None}
    else:
        return {'success': False, 'error': 'Failed to initialize TTS client. Check credentials.'}


# --- Environment Variable Bootstrap ---

def bootstrap_tts_from_env():
    """
    Bootstrap global TTS credentials from environment variables at startup.

    Checks two sources (in order):
    1. TDA_TTS_CREDENTIALS - Inline JSON string of Google service account credentials
    2. GOOGLE_APPLICATION_CREDENTIALS - File path to a Google service account JSON file

    Only activates when tts_mode is 'disabled' and no global credentials exist yet.
    When credentials are found, they are encrypted and stored in the DB, and
    tts_mode is set to 'global'.
    """
    current_mode = get_tts_mode()
    if current_mode != 'disabled':
        logger.debug(f"TTS bootstrap skipped: tts_mode is already '{current_mode}'")
        return

    if has_global_tts_credentials():
        logger.debug("TTS bootstrap skipped: global credentials already exist in DB")
        return

    credentials_json = None
    source = None

    # Source 1: Inline JSON from TDA_TTS_CREDENTIALS env var
    env_creds = os.environ.get('TDA_TTS_CREDENTIALS')
    if env_creds:
        try:
            json.loads(env_creds)  # Validate JSON
            credentials_json = env_creds
            source = 'TDA_TTS_CREDENTIALS env var'
        except json.JSONDecodeError:
            logger.error("TDA_TTS_CREDENTIALS env var contains invalid JSON - skipping TTS bootstrap")
            return

    # Source 2: File path from GOOGLE_APPLICATION_CREDENTIALS env var
    if not credentials_json:
        gac_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        if gac_path:
            try:
                with open(gac_path, 'r') as f:
                    file_content = f.read()
                json.loads(file_content)  # Validate JSON
                credentials_json = file_content
                source = f'GOOGLE_APPLICATION_CREDENTIALS file ({gac_path})'
            except FileNotFoundError:
                logger.error(f"GOOGLE_APPLICATION_CREDENTIALS file not found: {gac_path}")
                return
            except json.JSONDecodeError:
                logger.error(f"GOOGLE_APPLICATION_CREDENTIALS file contains invalid JSON: {gac_path}")
                return
            except Exception as e:
                logger.error(f"Error reading GOOGLE_APPLICATION_CREDENTIALS file: {e}")
                return

    if not credentials_json:
        logger.debug("TTS bootstrap: no credentials found in environment")
        return

    # Store credentials encrypted in DB and set mode to 'global'
    if save_global_tts_credentials(credentials_json):
        if set_tts_mode('global'):
            logger.info(f"TTS bootstrapped from {source}: mode set to 'global', credentials stored encrypted in DB")
        else:
            logger.error("TTS bootstrap: credentials saved but failed to set mode to 'global'")
    else:
        logger.error(f"TTS bootstrap: failed to save credentials from {source}")
