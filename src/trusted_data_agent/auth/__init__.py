"""
Authentication and authorization module for TDA.

This module provides user authentication, JWT token management,
and security features for multi-user environments.
"""

from trusted_data_agent.auth.database import init_database, get_db_session
from trusted_data_agent.auth.models import User, AuthToken, UserCredential, UserPreference, AuditLog, PasswordResetToken
from trusted_data_agent.auth.security import (
    hash_password,
    verify_password,
    generate_auth_token,
    verify_auth_token,
    revoke_token
)
from trusted_data_agent.auth.validators import (
    validate_username,
    validate_email,
    validate_registration_data,
    sanitize_user_input
)
from trusted_data_agent.auth.middleware import (
    require_auth,
    require_admin,
    optional_auth,
    get_current_user
)

__all__ = [
    # Database
    'init_database',
    'get_db_session',
    # Models
    'User',
    'AuthToken',
    'UserCredential',
    'UserPreference',
    'AuditLog',
    'PasswordResetToken',
    # Security
    'hash_password',
    'verify_password',
    'generate_auth_token',
    'verify_auth_token',
    'revoke_token',
    # Validators
    'validate_username',
    'validate_email',
    'validate_registration_data',
    'sanitize_user_input',
    # Middleware
    'require_auth',
    'require_admin',
    'optional_auth',
    'get_current_user'
]
