"""Admin utilities and permission checks for Phase 4.

Provides admin-only functionality including user management,
credential oversight, and system administration.

Profile Tier System:
- USER: Basic access (execute prompts, view own sessions)
- DEVELOPER: User access + advanced features (RAG, templates, testing)
- ADMIN: Full system access (user management, system config)
"""

import logging
from functools import wraps
from typing import Optional

from quart import request, jsonify

logger = logging.getLogger("quart.app")

# Profile tier constants
PROFILE_TIER_USER = "user"
PROFILE_TIER_DEVELOPER = "developer"
PROFILE_TIER_ADMIN = "admin"

# Tier hierarchy (higher index = higher privileges)
TIER_HIERARCHY = [PROFILE_TIER_USER, PROFILE_TIER_DEVELOPER, PROFILE_TIER_ADMIN]


def get_current_user_from_request():
    """
    Get current user from request context.
    
    Returns:
        User object or None
    """
    try:
        from trusted_data_agent.auth.middleware import get_current_user
        return get_current_user()
    except Exception as e:
        logger.warning(f"Failed to get current user: {e}")
        return None


def get_user_tier(user) -> str:
    """
    Get user's profile tier.
    
    Args:
        user: User object
        
    Returns:
        Profile tier ("user", "developer", or "admin")
    """
    if not user:
        return PROFILE_TIER_USER
    return getattr(user, 'profile_tier', PROFILE_TIER_USER)


def has_tier(user, required_tier: str) -> bool:
    """
    Check if user has required tier or higher (hierarchical).
    
    Args:
        user: User object
        required_tier: Minimum required tier
        
    Returns:
        True if user has required tier or higher
    """
    if not user:
        return False
    
    user_tier = get_user_tier(user)
    
    if user_tier not in TIER_HIERARCHY or required_tier not in TIER_HIERARCHY:
        return False
    
    return TIER_HIERARCHY.index(user_tier) >= TIER_HIERARCHY.index(required_tier)


def is_admin(user) -> bool:
    """
    Check if user has admin privileges.
    
    Args:
        user: User object
        
    Returns:
        True if user is admin tier
    """
    if not user:
        return False
    # Check both profile_tier and legacy is_admin flag
    return get_user_tier(user) == PROFILE_TIER_ADMIN or getattr(user, 'is_admin', False)


def is_developer(user) -> bool:
    """
    Check if user has developer privileges or higher.
    
    Args:
        user: User object
        
    Returns:
        True if user is developer or admin tier
    """
    return has_tier(user, PROFILE_TIER_DEVELOPER)


def require_tier(required_tier: str):
    """
    Decorator factory to require minimum profile tier for a route.
    
    Args:
        required_tier: Minimum tier required ("user", "developer", or "admin")
        
    Usage:
        @rest_api_bp.route('/api/v1/developer/rag')
        @require_tier('developer')
        async def manage_rag():
            ...
    """
    def decorator(f):
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            user = get_current_user_from_request()
            
            if not user:
                return jsonify({
                    "status": "error",
                    "message": "Authentication required"
                }), 401
            
            if not has_tier(user, required_tier):
                user_tier = get_user_tier(user)
                logger.warning(f"User {user.username} (tier: {user_tier}) attempted to access {required_tier} endpoint")
                return jsonify({
                    "status": "error",
                    "message": f"{required_tier.capitalize()} tier required"
                }), 403
            
            return await f(*args, **kwargs)
        
        return decorated_function
    return decorator


def require_admin(f):
    """
    Decorator to require admin privileges for a route.
    
    Usage:
        @rest_api_bp.route('/api/v1/admin/users')
        @require_admin
        async def list_users():
            ...
    """
    return require_tier(PROFILE_TIER_ADMIN)(f)


def require_developer(f):
    """
    Decorator to require developer privileges or higher for a route.
    
    Usage:
        @rest_api_bp.route('/api/v1/developer/templates')
        @require_developer
        async def manage_templates():
            ...
    """
    return require_tier(PROFILE_TIER_DEVELOPER)(f)


def can_manage_user(admin_user, target_user_id: str) -> bool:
    """
    Check if admin can manage a specific user.
    
    Prevents admins from modifying their own admin status.
    
    Args:
        admin_user: Admin user object
        target_user_id: Target user ID to manage
        
    Returns:
        True if management is allowed
    """
    if not admin_user or not is_admin(admin_user):
        return False
    
    # Prevent self-modification of admin status
    if admin_user.id == target_user_id:
        logger.warning(f"Admin {admin_user.username} attempted to modify their own account")
        return False
    
    return True
