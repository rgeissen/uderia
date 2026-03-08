"""
Feature tagging and access control system for profile tiers.

Defines all application features and their minimum required tier.
Use feature tags to enable/disable functionality based on user's profile tier.
"""

from enum import Enum
from typing import Set, Optional
from trusted_data_agent.auth.admin import (
    PROFILE_TIER_USER,
    PROFILE_TIER_DEVELOPER,
    PROFILE_TIER_ADMIN,
    get_user_tier,
    has_tier
)


class Feature(str, Enum):
    """
    Feature tags for all application capabilities.
    
    Each feature is tagged with its minimum required tier in FEATURE_TIER_MAP.
    """
    
    # ============================================================================
    # USER TIER FEATURES (Basic access - available to all authenticated users)
    # ============================================================================
    
    # Core Execution
    EXECUTE_PROMPTS = "execute_prompts"
    USE_MCP_TOOLS = "use_mcp_tools"
    VIEW_EXECUTION_RESULTS = "view_execution_results"
    
    # Session Management
    VIEW_OWN_SESSIONS = "view_own_sessions"
    DELETE_OWN_SESSIONS = "delete_own_sessions"
    EXPORT_OWN_SESSIONS = "export_own_sessions"
    
    # Credential Management
    STORE_CREDENTIALS = "store_credentials"
    USE_STORED_CREDENTIALS = "use_stored_credentials"
    DELETE_OWN_CREDENTIALS = "delete_own_credentials"
    
    # Configuration
    BASIC_CONFIGURATION = "basic_configuration"
    SELECT_PROVIDER = "select_provider"
    SELECT_MODEL = "select_model"
    SELECT_MCP_SERVER = "select_mcp_server"
    
    # Audit & Profile
    VIEW_OWN_AUDIT_LOGS = "view_own_audit_logs"
    UPDATE_OWN_PROFILE = "update_own_profile"
    CHANGE_OWN_PASSWORD = "change_own_password"
    
    # Voice & UI
    USE_VOICE_CONVERSATION = "use_voice_conversation"
    USE_CHARTING = "use_charting"
    BASIC_UI_ACCESS = "basic_ui_access"
    
    # ============================================================================
    # DEVELOPER TIER FEATURES (Advanced - developer and admin only)
    # ============================================================================
    
    # Session Analytics
    VIEW_ALL_SESSIONS = "view_all_sessions"
    EXPORT_ALL_SESSIONS = "export_all_sessions"
    SESSION_ANALYTICS = "session_analytics"
    
    # RAG Management
    CREATE_RAG_COLLECTIONS = "create_rag_collections"
    EDIT_RAG_COLLECTIONS = "edit_rag_collections"
    DELETE_RAG_COLLECTIONS = "delete_rag_collections"
    REFRESH_RAG_COLLECTIONS = "refresh_rag_collections"
    VIEW_RAG_STATISTICS = "view_rag_statistics"
    
    # Template Management
    CREATE_TEMPLATES = "create_templates"
    EDIT_TEMPLATES = "edit_templates"
    DELETE_TEMPLATES = "delete_templates"
    TEST_TEMPLATES = "test_templates"
    PUBLISH_TEMPLATES = "publish_templates"
    
    # MCP Testing & Development
    TEST_MCP_CONNECTIONS = "test_mcp_connections"
    VIEW_MCP_DIAGNOSTICS = "view_mcp_diagnostics"
    CONFIGURE_MCP_SERVERS = "configure_mcp_servers"
    
    # Advanced Configuration
    ADVANCED_CONFIGURATION = "advanced_configuration"
    CONFIGURE_OPTIMIZATION = "configure_optimization"
    CONFIGURE_RAG_SETTINGS = "configure_rag_settings"
    
    # Export & Import
    EXPORT_CONFIGURATIONS = "export_configurations"
    IMPORT_CONFIGURATIONS = "import_configurations"
    BULK_OPERATIONS = "bulk_operations"
    
    # Development Tools
    VIEW_DEBUG_LOGS = "view_debug_logs"
    ACCESS_API_DOCUMENTATION = "access_api_documentation"
    USE_DEVELOPER_CONSOLE = "use_developer_console"
    
    # ============================================================================
    # ADMIN TIER FEATURES (System administration - admin only)
    # ============================================================================
    
    # User Management
    VIEW_ALL_USERS = "view_all_users"
    CREATE_USERS = "create_users"
    EDIT_USERS = "edit_users"
    DELETE_USERS = "delete_users"
    UNLOCK_USERS = "unlock_users"
    CHANGE_USER_TIERS = "change_user_tiers"
    
    # Credential Oversight
    VIEW_ALL_CREDENTIALS = "view_all_credentials"
    DELETE_ANY_CREDENTIALS = "delete_any_credentials"
    
    # System Configuration
    MODIFY_GLOBAL_CONFIG = "modify_global_config"
    MANAGE_FEATURE_FLAGS = "manage_feature_flags"
    CONFIGURE_SECURITY = "configure_security"
    
    # System Monitoring
    VIEW_SYSTEM_STATS = "view_system_stats"
    VIEW_ALL_AUDIT_LOGS = "view_all_audit_logs"
    MONITOR_PERFORMANCE = "monitor_performance"
    VIEW_ERROR_LOGS = "view_error_logs"
    
    # Database Administration
    MANAGE_DATABASE = "manage_database"
    RUN_MIGRATIONS = "run_migrations"
    BACKUP_DATABASE = "backup_database"
    
    # Security & Compliance
    MANAGE_ENCRYPTION_KEYS = "manage_encryption_keys"
    CONFIGURE_AUTHENTICATION = "configure_authentication"
    MANAGE_AUDIT_SETTINGS = "manage_audit_settings"
    EXPORT_COMPLIANCE_REPORTS = "export_compliance_reports"


# ============================================================================
# FEATURE-TO-TIER MAPPING
# ============================================================================

FEATURE_TIER_MAP = {
    # USER TIER FEATURES
    Feature.EXECUTE_PROMPTS: PROFILE_TIER_USER,
    Feature.USE_MCP_TOOLS: PROFILE_TIER_USER,
    Feature.VIEW_EXECUTION_RESULTS: PROFILE_TIER_USER,
    Feature.VIEW_OWN_SESSIONS: PROFILE_TIER_USER,
    Feature.DELETE_OWN_SESSIONS: PROFILE_TIER_USER,
    Feature.EXPORT_OWN_SESSIONS: PROFILE_TIER_USER,
    Feature.STORE_CREDENTIALS: PROFILE_TIER_USER,
    Feature.USE_STORED_CREDENTIALS: PROFILE_TIER_USER,
    Feature.DELETE_OWN_CREDENTIALS: PROFILE_TIER_USER,
    Feature.BASIC_CONFIGURATION: PROFILE_TIER_USER,
    Feature.SELECT_PROVIDER: PROFILE_TIER_USER,
    Feature.SELECT_MODEL: PROFILE_TIER_USER,
    Feature.SELECT_MCP_SERVER: PROFILE_TIER_USER,
    Feature.VIEW_OWN_AUDIT_LOGS: PROFILE_TIER_USER,
    Feature.UPDATE_OWN_PROFILE: PROFILE_TIER_USER,
    Feature.CHANGE_OWN_PASSWORD: PROFILE_TIER_USER,
    Feature.USE_VOICE_CONVERSATION: PROFILE_TIER_USER,
    Feature.USE_CHARTING: PROFILE_TIER_USER,
    Feature.BASIC_UI_ACCESS: PROFILE_TIER_USER,
    
    # DEVELOPER TIER FEATURES
    Feature.VIEW_ALL_SESSIONS: PROFILE_TIER_DEVELOPER,
    Feature.EXPORT_ALL_SESSIONS: PROFILE_TIER_DEVELOPER,
    Feature.SESSION_ANALYTICS: PROFILE_TIER_DEVELOPER,
    Feature.CREATE_RAG_COLLECTIONS: PROFILE_TIER_DEVELOPER,
    Feature.EDIT_RAG_COLLECTIONS: PROFILE_TIER_DEVELOPER,
    Feature.DELETE_RAG_COLLECTIONS: PROFILE_TIER_DEVELOPER,
    Feature.REFRESH_RAG_COLLECTIONS: PROFILE_TIER_DEVELOPER,
    Feature.VIEW_RAG_STATISTICS: PROFILE_TIER_DEVELOPER,
    Feature.CREATE_TEMPLATES: PROFILE_TIER_DEVELOPER,
    Feature.EDIT_TEMPLATES: PROFILE_TIER_DEVELOPER,
    Feature.DELETE_TEMPLATES: PROFILE_TIER_DEVELOPER,
    Feature.TEST_TEMPLATES: PROFILE_TIER_DEVELOPER,
    Feature.PUBLISH_TEMPLATES: PROFILE_TIER_DEVELOPER,
    Feature.TEST_MCP_CONNECTIONS: PROFILE_TIER_DEVELOPER,
    Feature.VIEW_MCP_DIAGNOSTICS: PROFILE_TIER_DEVELOPER,
    Feature.CONFIGURE_MCP_SERVERS: PROFILE_TIER_DEVELOPER,
    Feature.ADVANCED_CONFIGURATION: PROFILE_TIER_DEVELOPER,
    Feature.CONFIGURE_OPTIMIZATION: PROFILE_TIER_DEVELOPER,
    Feature.CONFIGURE_RAG_SETTINGS: PROFILE_TIER_DEVELOPER,
    Feature.EXPORT_CONFIGURATIONS: PROFILE_TIER_DEVELOPER,
    Feature.IMPORT_CONFIGURATIONS: PROFILE_TIER_DEVELOPER,
    Feature.BULK_OPERATIONS: PROFILE_TIER_DEVELOPER,
    Feature.VIEW_DEBUG_LOGS: PROFILE_TIER_DEVELOPER,
    Feature.ACCESS_API_DOCUMENTATION: PROFILE_TIER_DEVELOPER,
    Feature.USE_DEVELOPER_CONSOLE: PROFILE_TIER_DEVELOPER,
    
    # ADMIN TIER FEATURES
    Feature.VIEW_ALL_USERS: PROFILE_TIER_ADMIN,
    Feature.CREATE_USERS: PROFILE_TIER_ADMIN,
    Feature.EDIT_USERS: PROFILE_TIER_ADMIN,
    Feature.DELETE_USERS: PROFILE_TIER_ADMIN,
    Feature.UNLOCK_USERS: PROFILE_TIER_ADMIN,
    Feature.CHANGE_USER_TIERS: PROFILE_TIER_ADMIN,
    Feature.VIEW_ALL_CREDENTIALS: PROFILE_TIER_ADMIN,
    Feature.DELETE_ANY_CREDENTIALS: PROFILE_TIER_ADMIN,
    Feature.MODIFY_GLOBAL_CONFIG: PROFILE_TIER_ADMIN,
    Feature.MANAGE_FEATURE_FLAGS: PROFILE_TIER_ADMIN,
    Feature.CONFIGURE_SECURITY: PROFILE_TIER_ADMIN,
    Feature.VIEW_SYSTEM_STATS: PROFILE_TIER_ADMIN,
    Feature.VIEW_ALL_AUDIT_LOGS: PROFILE_TIER_ADMIN,
    Feature.MONITOR_PERFORMANCE: PROFILE_TIER_ADMIN,
    Feature.VIEW_ERROR_LOGS: PROFILE_TIER_ADMIN,
    Feature.MANAGE_DATABASE: PROFILE_TIER_ADMIN,
    Feature.RUN_MIGRATIONS: PROFILE_TIER_ADMIN,
    Feature.BACKUP_DATABASE: PROFILE_TIER_ADMIN,
    Feature.MANAGE_ENCRYPTION_KEYS: PROFILE_TIER_ADMIN,
    Feature.CONFIGURE_AUTHENTICATION: PROFILE_TIER_ADMIN,
    Feature.MANAGE_AUDIT_SETTINGS: PROFILE_TIER_ADMIN,
    Feature.EXPORT_COMPLIANCE_REPORTS: PROFILE_TIER_ADMIN,
}


# ============================================================================
# FEATURE ACCESS FUNCTIONS
# ============================================================================

def user_has_feature(user, feature: Feature) -> bool:
    """
    Check if user has access to a specific feature.
    
    Args:
        user: User object
        feature: Feature enum value
        
    Returns:
        True if user's tier allows access to this feature
        
    Example:
        if user_has_feature(current_user, Feature.CREATE_RAG_COLLECTIONS):
            # Show RAG creation UI
            ...
    """
    if not user:
        return False
    
    required_tier = FEATURE_TIER_MAP.get(feature)
    if not required_tier:
        return False
    
    return has_tier(user, required_tier)


def get_user_features(user) -> Set[Feature]:
    """
    Get all features available to a user based on their tier.
    
    Args:
        user: User object
        
    Returns:
        Set of Feature enum values the user can access
        
    Example:
        features = get_user_features(current_user)
        if Feature.CREATE_TEMPLATES in features:
            # Enable template creation
            ...
    """
    if not user:
        return set()
    
    user_tier = get_user_tier(user)
    available_features = set()
    
    for feature, required_tier in FEATURE_TIER_MAP.items():
        if has_tier(user, required_tier):
            available_features.add(feature)
    
    return available_features


def get_features_by_tier(tier: str) -> Set[Feature]:
    """
    Get all features available at a specific tier (including inherited features).
    
    Args:
        tier: Profile tier ('user', 'developer', or 'admin')
        
    Returns:
        Set of Feature enum values available at this tier
        
    Example:
        dev_features = get_features_by_tier('developer')
        print(f"Developer tier has {len(dev_features)} features")
    """
    available_features = set()
    
    for feature, required_tier in FEATURE_TIER_MAP.items():
        # Check if this tier meets the requirement (hierarchical)
        from trusted_data_agent.auth.admin import TIER_HIERARCHY
        if (tier in TIER_HIERARCHY and 
            required_tier in TIER_HIERARCHY and
            TIER_HIERARCHY.index(tier) >= TIER_HIERARCHY.index(required_tier)):
            available_features.add(feature)
    
    return available_features


def require_feature(feature: Feature):
    """
    Decorator to require a specific feature for an endpoint or function.
    
    Args:
        feature: Feature enum value required
        
    Usage:
        @rest_api_bp.route('/api/v1/rag/collections')
        @require_feature(Feature.CREATE_RAG_COLLECTIONS)
        async def create_rag_collection():
            ...
    """
    from functools import wraps
    from quart import jsonify
    
    def decorator(f):
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            from trusted_data_agent.auth.admin import get_current_user_from_request
            
            user = get_current_user_from_request()
            
            if not user:
                return jsonify({
                    "status": "error",
                    "message": "Authentication required"
                }), 401
            
            if not user_has_feature(user, feature):
                user_tier = get_user_tier(user)
                required_tier = FEATURE_TIER_MAP.get(feature)
                return jsonify({
                    "status": "error",
                    "message": f"Feature '{feature.value}' requires {required_tier} tier (you have {user_tier})"
                }), 403
            
            return await f(*args, **kwargs)
        
        return decorated_function
    return decorator


def get_feature_info() -> dict:
    """
    Get comprehensive feature information for documentation/UI.
    
    Returns:
        Dictionary with feature categories and their required tiers
        
    Example:
        info = get_feature_info()
        for tier, features in info['by_tier'].items():
            print(f"{tier}: {len(features)} features")
    """
    by_tier = {
        PROFILE_TIER_USER: [],
        PROFILE_TIER_DEVELOPER: [],
        PROFILE_TIER_ADMIN: []
    }
    
    for feature, tier in FEATURE_TIER_MAP.items():
        by_tier[tier].append({
            "name": feature.value,
            "enum": feature.name,
            "required_tier": tier
        })
    
    return {
        "total_features": len(FEATURE_TIER_MAP),
        "by_tier": by_tier,
        "tier_counts": {
            tier: len(features) for tier, features in by_tier.items()
        }
    }


# ============================================================================
# FEATURE GROUPS (for bulk checking)
# ============================================================================

FEATURE_GROUPS = {
    "session_management": {
        Feature.VIEW_OWN_SESSIONS,
        Feature.DELETE_OWN_SESSIONS,
        Feature.EXPORT_OWN_SESSIONS,
        Feature.VIEW_ALL_SESSIONS,
        Feature.EXPORT_ALL_SESSIONS,
        Feature.SESSION_ANALYTICS,
    },
    "rag_management": {
        Feature.CREATE_RAG_COLLECTIONS,
        Feature.EDIT_RAG_COLLECTIONS,
        Feature.DELETE_RAG_COLLECTIONS,
        Feature.REFRESH_RAG_COLLECTIONS,
        Feature.VIEW_RAG_STATISTICS,
    },
    "template_management": {
        Feature.CREATE_TEMPLATES,
        Feature.EDIT_TEMPLATES,
        Feature.DELETE_TEMPLATES,
        Feature.TEST_TEMPLATES,
        Feature.PUBLISH_TEMPLATES,
    },
    "user_management": {
        Feature.VIEW_ALL_USERS,
        Feature.CREATE_USERS,
        Feature.EDIT_USERS,
        Feature.DELETE_USERS,
        Feature.UNLOCK_USERS,
        Feature.CHANGE_USER_TIERS,
    },
    "system_admin": {
        Feature.VIEW_SYSTEM_STATS,
        Feature.VIEW_ALL_AUDIT_LOGS,
        Feature.MONITOR_PERFORMANCE,
        Feature.VIEW_ERROR_LOGS,
        Feature.MANAGE_DATABASE,
        Feature.CONFIGURE_SECURITY,
    },
}


def user_has_feature_group(user, group_name: str) -> bool:
    """
    Check if user has access to ANY feature in a feature group.
    
    Args:
        user: User object
        group_name: Name of feature group
        
    Returns:
        True if user has at least one feature from the group
    """
    if not user or group_name not in FEATURE_GROUPS:
        return False
    
    features = FEATURE_GROUPS[group_name]
    return any(user_has_feature(user, feature) for feature in features)


def user_has_all_features_in_group(user, group_name: str) -> bool:
    """
    Check if user has access to ALL features in a feature group.
    
    Args:
        user: User object
        group_name: Name of feature group
        
    Returns:
        True if user has all features from the group
    """
    if not user or group_name not in FEATURE_GROUPS:
        return False
    
    features = FEATURE_GROUPS[group_name]
    return all(user_has_feature(user, feature) for feature in features)


def get_feature_info() -> list:
    """
    Get detailed information about all features for admin UI.
    
    Returns:
        List of feature dictionaries with metadata
    """
    feature_categories = {
        # Core Execution
        Feature.EXECUTE_PROMPTS: ("Core Execution", "Execute AI prompts"),
        Feature.USE_MCP_TOOLS: ("Core Execution", "Use Model Context Protocol tools"),
        Feature.VIEW_EXECUTION_RESULTS: ("Core Execution", "View execution results"),
        
        # Session Management
        Feature.VIEW_OWN_SESSIONS: ("Session Management", "View own session history"),
        Feature.DELETE_OWN_SESSIONS: ("Session Management", "Delete own sessions"),
        Feature.EXPORT_OWN_SESSIONS: ("Session Management", "Export own sessions"),
        Feature.VIEW_ALL_SESSIONS: ("Session Management", "View all users' sessions"),
        Feature.EXPORT_ALL_SESSIONS: ("Session Management", "Export all sessions"),
        Feature.SESSION_ANALYTICS: ("Session Management", "Advanced session analytics"),
        
        # Credentials
        Feature.STORE_CREDENTIALS: ("Credentials", "Store encrypted credentials"),
        Feature.USE_STORED_CREDENTIALS: ("Credentials", "Use auto-load credentials"),
        Feature.DELETE_OWN_CREDENTIALS: ("Credentials", "Delete own credentials"),
        Feature.VIEW_ALL_CREDENTIALS: ("Credentials", "View all users' credentials"),
        Feature.DELETE_ANY_CREDENTIALS: ("Credentials", "Delete any user's credentials"),
        
        # Configuration
        Feature.BASIC_CONFIGURATION: ("Configuration", "Basic settings configuration"),
        Feature.SELECT_PROVIDER: ("Configuration", "Choose AI provider"),
        Feature.SELECT_MODEL: ("Configuration", "Choose AI model"),
        Feature.SELECT_MCP_SERVER: ("Configuration", "Choose MCP server"),
        Feature.ADVANCED_CONFIGURATION: ("Configuration", "Advanced settings"),
        Feature.CONFIGURE_OPTIMIZATION: ("Configuration", "Optimization settings"),
        Feature.CONFIGURE_RAG_SETTINGS: ("Configuration", "RAG configuration"),
        Feature.CONFIGURE_MCP_SERVERS: ("Configuration", "MCP server management"),
        Feature.MODIFY_GLOBAL_CONFIG: ("Configuration", "System-wide settings"),
        Feature.CONFIGURE_SECURITY: ("Configuration", "Security settings"),
        Feature.CONFIGURE_AUTHENTICATION: ("Configuration", "Authentication settings"),
        
        # RAG Management
        Feature.CREATE_RAG_COLLECTIONS: ("RAG Management", "Create RAG collections"),
        Feature.EDIT_RAG_COLLECTIONS: ("RAG Management", "Edit RAG collections"),
        Feature.DELETE_RAG_COLLECTIONS: ("RAG Management", "Delete RAG collections"),
        Feature.REFRESH_RAG_COLLECTIONS: ("RAG Management", "Refresh vector store"),
        Feature.VIEW_RAG_STATISTICS: ("RAG Management", "View RAG statistics"),
        
        # Templates
        Feature.CREATE_TEMPLATES: ("Templates", "Create new templates"),
        Feature.EDIT_TEMPLATES: ("Templates", "Edit existing templates"),
        Feature.DELETE_TEMPLATES: ("Templates", "Delete templates"),
        Feature.TEST_TEMPLATES: ("Templates", "Test template functionality"),
        Feature.PUBLISH_TEMPLATES: ("Templates", "Publish templates"),
        
        # User Management
        Feature.VIEW_ALL_USERS: ("User Management", "View all users"),
        Feature.CREATE_USERS: ("User Management", "Create new users"),
        Feature.EDIT_USERS: ("User Management", "Edit user details"),
        Feature.DELETE_USERS: ("User Management", "Delete/deactivate users"),
        Feature.UNLOCK_USERS: ("User Management", "Unlock locked accounts"),
        Feature.CHANGE_USER_TIERS: ("User Management", "Change user profile tiers"),
        
        # Profile & Audit
        Feature.VIEW_OWN_AUDIT_LOGS: ("Audit & Profile", "View own audit logs"),
        Feature.VIEW_ALL_AUDIT_LOGS: ("Audit & Profile", "View all audit logs"),
        Feature.UPDATE_OWN_PROFILE: ("Audit & Profile", "Update own profile"),
        Feature.CHANGE_OWN_PASSWORD: ("Audit & Profile", "Change own password"),
        
        # System Admin
        Feature.VIEW_SYSTEM_STATS: ("System Administration", "View system statistics"),
        Feature.MONITOR_PERFORMANCE: ("System Administration", "Monitor system performance"),
        Feature.VIEW_ERROR_LOGS: ("System Administration", "View error logs"),
        Feature.MANAGE_DATABASE: ("System Administration", "Database administration"),
        Feature.RUN_MIGRATIONS: ("System Administration", "Run schema migrations"),
        Feature.BACKUP_DATABASE: ("System Administration", "Database backups"),
        Feature.MANAGE_FEATURE_FLAGS: ("System Administration", "Control feature availability"),
        Feature.MANAGE_ENCRYPTION_KEYS: ("System Administration", "Encryption key management"),
        Feature.MANAGE_AUDIT_SETTINGS: ("System Administration", "Audit settings"),
        Feature.EXPORT_COMPLIANCE_REPORTS: ("System Administration", "Compliance reporting"),
        
        # Import/Export
        Feature.EXPORT_CONFIGURATIONS: ("Import/Export", "Export configurations"),
        Feature.IMPORT_CONFIGURATIONS: ("Import/Export", "Import configurations"),
        Feature.BULK_OPERATIONS: ("Import/Export", "Bulk operations"),
        
        # Developer Tools
        Feature.VIEW_DEBUG_LOGS: ("Developer Tools", "View debug logs"),
        Feature.ACCESS_API_DOCUMENTATION: ("Developer Tools", "API documentation access"),
        Feature.USE_DEVELOPER_CONSOLE: ("Developer Tools", "Developer console"),
        Feature.TEST_MCP_CONNECTIONS: ("Developer Tools", "Test MCP connections"),
        Feature.VIEW_MCP_DIAGNOSTICS: ("Developer Tools", "View MCP diagnostics"),
        
        # UI Features
        Feature.USE_VOICE_CONVERSATION: ("UI Features", "Voice conversation"),
        Feature.USE_CHARTING: ("UI Features", "Charting functionality"),
        Feature.BASIC_UI_ACCESS: ("UI Features", "Basic UI access"),
    }
    
    features_list = []
    for feature in Feature:
        category, description = feature_categories.get(feature, ("Other", ""))
        required_tier = FEATURE_TIER_MAP.get(feature, PROFILE_TIER_USER)
        
        # Convert enum name to display name
        display_name = feature.value.replace('_', ' ').title()
        
        features_list.append({
            "name": feature.value,
            "display_name": display_name,
            "required_tier": required_tier,
            "category": category,
            "description": description
        })
    
    return sorted(features_list, key=lambda x: (x["category"], x["name"]))


def get_default_feature_tier_map():
    """
    Get the default feature-to-tier mappings.
    Used for resetting feature configurations.
    
    Returns:
        Dictionary mapping Feature enum to tier string
    """
    # This is the original default mapping
    return {
        # USER TIER (19 features)
        Feature.EXECUTE_PROMPTS: PROFILE_TIER_USER,
        Feature.USE_MCP_TOOLS: PROFILE_TIER_USER,
        Feature.VIEW_EXECUTION_RESULTS: PROFILE_TIER_USER,
        Feature.VIEW_OWN_SESSIONS: PROFILE_TIER_USER,
        Feature.DELETE_OWN_SESSIONS: PROFILE_TIER_USER,
        Feature.EXPORT_OWN_SESSIONS: PROFILE_TIER_USER,
        Feature.STORE_CREDENTIALS: PROFILE_TIER_USER,
        Feature.USE_STORED_CREDENTIALS: PROFILE_TIER_USER,
        Feature.DELETE_OWN_CREDENTIALS: PROFILE_TIER_USER,
        Feature.BASIC_CONFIGURATION: PROFILE_TIER_USER,
        Feature.SELECT_PROVIDER: PROFILE_TIER_USER,
        Feature.SELECT_MODEL: PROFILE_TIER_USER,
        Feature.SELECT_MCP_SERVER: PROFILE_TIER_USER,
        Feature.VIEW_OWN_AUDIT_LOGS: PROFILE_TIER_USER,
        Feature.UPDATE_OWN_PROFILE: PROFILE_TIER_USER,
        Feature.CHANGE_OWN_PASSWORD: PROFILE_TIER_USER,
        Feature.USE_VOICE_CONVERSATION: PROFILE_TIER_USER,
        Feature.USE_CHARTING: PROFILE_TIER_USER,
        Feature.BASIC_UI_ACCESS: PROFILE_TIER_USER,
        
        # DEVELOPER TIER (25 features)
        Feature.VIEW_ALL_SESSIONS: PROFILE_TIER_DEVELOPER,
        Feature.EXPORT_ALL_SESSIONS: PROFILE_TIER_DEVELOPER,
        Feature.SESSION_ANALYTICS: PROFILE_TIER_DEVELOPER,
        Feature.CREATE_RAG_COLLECTIONS: PROFILE_TIER_DEVELOPER,
        Feature.EDIT_RAG_COLLECTIONS: PROFILE_TIER_DEVELOPER,
        Feature.DELETE_RAG_COLLECTIONS: PROFILE_TIER_DEVELOPER,
        Feature.REFRESH_RAG_COLLECTIONS: PROFILE_TIER_DEVELOPER,
        Feature.VIEW_RAG_STATISTICS: PROFILE_TIER_DEVELOPER,
        Feature.CREATE_TEMPLATES: PROFILE_TIER_DEVELOPER,
        Feature.EDIT_TEMPLATES: PROFILE_TIER_DEVELOPER,
        Feature.DELETE_TEMPLATES: PROFILE_TIER_DEVELOPER,
        Feature.TEST_TEMPLATES: PROFILE_TIER_DEVELOPER,
        Feature.PUBLISH_TEMPLATES: PROFILE_TIER_DEVELOPER,
        Feature.TEST_MCP_CONNECTIONS: PROFILE_TIER_DEVELOPER,
        Feature.VIEW_MCP_DIAGNOSTICS: PROFILE_TIER_DEVELOPER,
        Feature.CONFIGURE_MCP_SERVERS: PROFILE_TIER_DEVELOPER,
        Feature.ADVANCED_CONFIGURATION: PROFILE_TIER_DEVELOPER,
        Feature.CONFIGURE_OPTIMIZATION: PROFILE_TIER_DEVELOPER,
        Feature.CONFIGURE_RAG_SETTINGS: PROFILE_TIER_DEVELOPER,
        Feature.EXPORT_CONFIGURATIONS: PROFILE_TIER_DEVELOPER,
        Feature.IMPORT_CONFIGURATIONS: PROFILE_TIER_DEVELOPER,
        Feature.BULK_OPERATIONS: PROFILE_TIER_DEVELOPER,
        Feature.VIEW_DEBUG_LOGS: PROFILE_TIER_DEVELOPER,
        Feature.ACCESS_API_DOCUMENTATION: PROFILE_TIER_DEVELOPER,
        Feature.USE_DEVELOPER_CONSOLE: PROFILE_TIER_DEVELOPER,
        
        # ADMIN TIER (22 features)
        Feature.VIEW_ALL_USERS: PROFILE_TIER_ADMIN,
        Feature.CREATE_USERS: PROFILE_TIER_ADMIN,
        Feature.EDIT_USERS: PROFILE_TIER_ADMIN,
        Feature.DELETE_USERS: PROFILE_TIER_ADMIN,
        Feature.UNLOCK_USERS: PROFILE_TIER_ADMIN,
        Feature.CHANGE_USER_TIERS: PROFILE_TIER_ADMIN,
        Feature.VIEW_ALL_CREDENTIALS: PROFILE_TIER_ADMIN,
        Feature.DELETE_ANY_CREDENTIALS: PROFILE_TIER_ADMIN,
        Feature.MODIFY_GLOBAL_CONFIG: PROFILE_TIER_ADMIN,
        Feature.MANAGE_FEATURE_FLAGS: PROFILE_TIER_ADMIN,
        Feature.CONFIGURE_SECURITY: PROFILE_TIER_ADMIN,
        Feature.VIEW_SYSTEM_STATS: PROFILE_TIER_ADMIN,
        Feature.VIEW_ALL_AUDIT_LOGS: PROFILE_TIER_ADMIN,
        Feature.MONITOR_PERFORMANCE: PROFILE_TIER_ADMIN,
        Feature.VIEW_ERROR_LOGS: PROFILE_TIER_ADMIN,
        Feature.MANAGE_DATABASE: PROFILE_TIER_ADMIN,
        Feature.RUN_MIGRATIONS: PROFILE_TIER_ADMIN,
        Feature.BACKUP_DATABASE: PROFILE_TIER_ADMIN,
        Feature.MANAGE_ENCRYPTION_KEYS: PROFILE_TIER_ADMIN,
        Feature.CONFIGURE_AUTHENTICATION: PROFILE_TIER_ADMIN,
        Feature.MANAGE_AUDIT_SETTINGS: PROFILE_TIER_ADMIN,
        Feature.EXPORT_COMPLIANCE_REPORTS: PROFILE_TIER_ADMIN,
    }
