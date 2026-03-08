"""
Custom exceptions for the authentication and authorization module.
"""

class AuthException(Exception):
    """Base exception for authentication errors."""
    pass

class UserDeactivatedException(AuthException):
    """Raised when a deactivated user attempts to log in."""
    pass
