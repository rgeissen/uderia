"""
Input validators for authentication.

Validates usernames, emails, passwords, and sanitizes user input.
"""

import re
import logging
from typing import Tuple, List
from email_validator import validate_email as validate_email_lib, EmailNotValidError

logger = logging.getLogger("quart.app")

# Validation patterns
USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{3,30}$')
# Dangerous patterns for SQL injection and XSS
SQL_INJECTION_PATTERNS = [
    r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE)\b)",
    r"(--|\#|\/\*|\*\/)",
    r"(\bOR\b.*=.*)",
    r"(\bAND\b.*=.*)",
]
XSS_PATTERNS = [
    r"<script[^>]*>.*?</script>",
    r"javascript:",
    r"on\w+\s*=",
]


def validate_username(username: str) -> Tuple[bool, List[str]]:
    """
    Validate username format.
    
    Rules:
    - 3-30 characters
    - Alphanumeric and underscore only
    - Cannot be empty or whitespace
    
    Args:
        username: Username to validate
        
    Returns:
        Tuple of (is_valid, [error_messages])
    """
    errors = []
    
    if not username:
        errors.append("Username cannot be empty")
        return False, errors
    
    if not USERNAME_PATTERN.match(username):
        if len(username) < 3:
            errors.append("Username must be at least 3 characters long")
        elif len(username) > 30:
            errors.append("Username must be at most 30 characters long")
        else:
            errors.append("Username can only contain letters, numbers, and underscores")
    
    # Check for dangerous patterns
    username_lower = username.lower()
    for pattern in SQL_INJECTION_PATTERNS:
        if re.search(pattern, username_lower, re.IGNORECASE):
            errors.append("Username contains invalid characters")
            break
    
    return len(errors) == 0, errors


def validate_email(email: str) -> Tuple[bool, List[str]]:
    """
    Validate email address format.
    
    Uses email_validator library for RFC 5322 compliance.
    
    Args:
        email: Email address to validate
        
    Returns:
        Tuple of (is_valid, [error_messages])
    """
    errors = []
    
    if not email:
        errors.append("Email cannot be empty")
        return False, errors
    
    try:
        # Validate and normalize email
        validated = validate_email_lib(email, check_deliverability=False)
        # Could use validated.normalized for storage if needed
        return True, []
    except EmailNotValidError as e:
        errors.append(str(e))
        return False, errors


def sanitize_user_input(text: str, max_length: int = 1000) -> str:
    """
    Sanitize user input to prevent SQL injection and XSS attacks.
    
    Note: This is defense-in-depth. Primary protection comes from:
    - Parameterized queries (SQLAlchemy handles this)
    - Proper output escaping in templates
    
    Args:
        text: User input text
        max_length: Maximum allowed length
        
    Returns:
        Sanitized text (empty string if dangerous patterns detected)
    """
    if not text:
        return ""
    
    # Truncate to max length
    text = text[:max_length]
    
    # Check for SQL injection patterns
    for pattern in SQL_INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Potential SQL injection attempt detected: {pattern}")
            return ""
    
    # Check for XSS patterns
    for pattern in XSS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Potential XSS attempt detected: {pattern}")
            return ""
    
    # Strip dangerous HTML/script tags
    text = re.sub(r'<[^>]+>', '', text)
    
    return text.strip()


def validate_registration_data(username: str, email: str, password: str) -> Tuple[bool, List[str]]:
    """
    Validate all registration data at once.
    
    Args:
        username: Username
        email: Email address
        password: Password
        
    Returns:
        Tuple of (is_valid, [error_messages])
    """
    from trusted_data_agent.auth.security import validate_password_strength
    
    all_errors = []
    
    # Validate username
    username_valid, username_errors = validate_username(username)
    all_errors.extend(username_errors)
    
    # Validate email
    email_valid, email_errors = validate_email(email)
    all_errors.extend(email_errors)
    
    # Validate password
    password_valid, password_errors = validate_password_strength(password)
    all_errors.extend(password_errors)
    
    return len(all_errors) == 0, all_errors
