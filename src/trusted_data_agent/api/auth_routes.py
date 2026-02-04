"""
Authentication REST API routes.

Provides endpoints for user registration, login, logout, and profile management.
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Any

from quart import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, AuthToken, AuditLog
from trusted_data_agent.auth.security import (
    hash_password,
    verify_password,
    generate_auth_token,
    verify_auth_token,
    revoke_token,
    check_user_lockout,
    check_progressive_delay,
    get_login_status,
    record_failed_login,
    reset_failed_login_attempts,
    MAX_LOGIN_ATTEMPTS
)
from trusted_data_agent.auth.validators import (
    validate_registration_data,
    validate_username,
    validate_email,
    sanitize_user_input
)
from trusted_data_agent.auth.middleware import (
    require_auth,
    require_admin,
    get_request_context,
    get_current_user
)
from trusted_data_agent.auth.rate_limiter import check_ip_login_limit, check_ip_register_limit
from trusted_data_agent.auth.audit import (
    log_audit_event as log_audit_event_detailed,
    log_login_success,
    log_login_failure,
    log_registration,
    log_rate_limit_exceeded
)
from trusted_data_agent.auth.email_verification import EmailVerificationService
from trusted_data_agent.auth.email_service import EmailService

logger = logging.getLogger("quart.app")

# Create Blueprint
auth_bp = Blueprint('auth', __name__, url_prefix='/api/v1/auth')


def _ensure_user_default_collection(user_id: str, mcp_servers: list):
    """
    Ensure a user has a Default Collection for EACH MCP server.
    This is called during first login bootstrap.
    If created, reloads collections into APP_STATE and RAG retriever so it's immediately available.
    """
    from trusted_data_agent.core.collection_db import get_collection_db
    from trusted_data_agent.core.config_manager import get_config_manager
    from trusted_data_agent.core.config import APP_STATE
    from trusted_data_agent.agent.rag_retriever import get_rag_retriever
    from datetime import datetime, timezone
    import uuid

    logger.info(f"_ensure_user_default_collection called for user {user_id} with {len(mcp_servers)} MCP servers")

    try:
        collection_db = get_collection_db()

        # Get existing collections for this user
        user_collections = collection_db.get_user_owned_collections(user_id)

        # Track which MCP servers already have default collections
        existing_server_ids = set()
        for collection in user_collections:
            if 'Default Collection' in collection.get('name', '') and collection.get('repository_type') == 'planner':
                existing_server_ids.add(collection.get('mcp_server_id'))

        collections_created = []

        # Create a default collection for EACH MCP server that doesn't have one
        for mcp_server in mcp_servers:
            mcp_server_id = mcp_server.get('id')
            mcp_server_name = mcp_server.get('name', 'Unknown Server')

            if not mcp_server_id:
                logger.warning(f"Skipping MCP server without ID: {mcp_server}")
                continue

            # Skip if this server already has a default collection
            if mcp_server_id in existing_server_ids:
                logger.debug(f"MCP server '{mcp_server_name}' (ID: {mcp_server_id}) already has a default collection")
                continue

            # Create default collection for this MCP server
            collection_name = f"Default Collection - {mcp_server_name}"
            collection_data = {
                'name': collection_name,
                'collection_name': f'tda_rag_coll_default_{uuid.uuid4().hex[:6]}',
                'mcp_server_id': mcp_server_id,
                'enabled': True,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'description': f'Default planner repository for MCP server: {mcp_server_name}',
                'owner_user_id': user_id,
                'visibility': 'private',
                'is_marketplace_listed': False,
                'subscriber_count': 0,
                'marketplace_metadata': {},
                'repository_type': 'planner',
                'embedding_model': 'all-MiniLM-L6-v2'
            }

            collection_id = collection_db.create_collection(collection_data)
            if collection_id:
                logger.info(f"Created default collection '{collection_name}' (ID: {collection_id}) for MCP server '{mcp_server_name}' (ID: {mcp_server_id})")
                collections_created.append(collection_id)
            else:
                logger.warning(f"Failed to create default collection for MCP server '{mcp_server_name}'")

        # If any collections were created, reload APP_STATE and RAG retriever
        if collections_created:
            logger.info(f"Created {len(collections_created)} default collections for user {user_id}")

            # Reload collections into APP_STATE so they're immediately available
            config_manager = get_config_manager()
            collections_list = config_manager.get_rag_collections()
            APP_STATE["rag_collections"] = collections_list
            logger.info(f"Reloaded {len(collections_list)} collections into APP_STATE after creating default collections")

            # Reload the new collections into the RAG retriever's memory
            retriever = get_rag_retriever()
            if retriever:
                for collection_id in collections_created:
                    try:
                        # Get the newly created collection metadata
                        new_collection = collection_db.get_collection_by_id(collection_id)
                        if new_collection and new_collection.get('enabled', False):
                            collection_name = new_collection['collection_name']
                            # Load it into ChromaDB
                            chroma_collection = retriever.client.get_or_create_collection(
                                name=collection_name,
                                embedding_function=retriever.embedding_function,
                                metadata={"hnsw:space": "cosine"}
                            )
                            retriever.collections[collection_id] = chroma_collection
                            logger.info(f"Loaded new default collection (ID: {collection_id}) into RAG retriever")
                    except Exception as load_err:
                        logger.error(f"Failed to load default collection {collection_id} into RAG retriever: {load_err}", exc_info=True)

            # Build mapping of mcp_server_id -> collection_id for profile updates
            collection_ids_by_server = {}
            for collection_id in collections_created:
                collection = collection_db.get_collection_by_id(collection_id)
                if collection:
                    server_id = collection.get('mcp_server_id')
                    if server_id:
                        collection_ids_by_server[server_id] = collection_id

            # Update profiles to enable autocomplete for default collections
            if collection_ids_by_server:
                logger.info(f"Updating profiles with {len(collection_ids_by_server)} default collection(s) for autocomplete")
                _update_profiles_with_default_collections(user_id, collection_ids_by_server)
        else:
            logger.debug(f"No new default collections needed for user {user_id} - all MCP servers already have collections")
            
    except Exception as e:
        logger.error(f"Error creating Default Collection for user {user_id}: {e}", exc_info=True)


def _update_profiles_with_default_collections(user_id: str, collection_ids_by_server: dict) -> bool:
    """
    Update all user profiles to enable autocomplete and RAG for their default collections.

    This function is called during user bootstrap (first login) after default
    planner collections are created. It ensures that each profile's
    autocompleteCollections and ragCollections arrays contain the collection ID
    for its associated MCP server's default collection.

    Mapping Logic:
        - For each profile with mcpServerId != null:
            - Find the default collection for that MCP server
            - Add collection ID to profile.autocompleteCollections (all profiles)
            - Add collection ID to profile.ragCollections (tool_enabled profiles only)
        - Profiles with mcpServerId == null (e.g., @CHAT) are skipped

    Args:
        user_id: User UUID
        collection_ids_by_server: Mapping of {mcp_server_id: collection_id}
                                 Example: {"1763483266562-a6kulj4xc": 123}

    Returns:
        True if profiles were updated successfully, False on error

    Example:
        >>> collection_ids_by_server = {"server-123": 456}
        >>> _update_profiles_with_default_collections("user-789", collection_ids_by_server)
        True

        Result: Profile with mcpServerId="server-123" now has autocompleteCollections=[456]
    """
    from trusted_data_agent.core.config_manager import get_config_manager

    try:
        config_manager = get_config_manager()
        profiles = config_manager.get_profiles(user_id)

        updated_count = 0
        for profile in profiles:
            mcp_server_id = profile.get("mcpServerId")

            # Skip profiles without MCP server (e.g., @CHAT llm-only)
            if not mcp_server_id:
                logger.debug(f"Skipping profile @{profile.get('tag')} - no mcpServerId")
                continue

            # Check if this MCP server has a default collection
            if mcp_server_id in collection_ids_by_server:
                collection_id = collection_ids_by_server[mcp_server_id]
                autocomplete_colls = profile.get("autocompleteCollections", [])

                # Add if not already present (idempotent)
                if collection_id not in autocomplete_colls:
                    autocomplete_colls.append(collection_id)
                    profile["autocompleteCollections"] = autocomplete_colls
                    updated_count += 1
                    logger.info(f"✅ Enabled autocomplete for profile @{profile.get('tag')} → Collection {collection_id}")

                # Also populate ragCollections for tool_enabled profiles
                # (used for RAG retrieval filtering during strategic planning)
                profile_type = profile.get("profile_type", "")
                if profile_type == "tool_enabled":
                    rag_colls = profile.get("ragCollections", [])

                    # Add collection ID if not already present (idempotent)
                    if collection_id not in rag_colls:
                        rag_colls.append(collection_id)
                        profile["ragCollections"] = rag_colls
                        logger.info(
                            f"✅ Added collection {collection_id} to ragCollections "
                            f"for tool_enabled profile @{profile.get('tag')}"
                        )

        if updated_count > 0:
            success = config_manager.save_profiles(profiles, user_id)
            if success:
                logger.info(f"Updated {updated_count} profiles with default collections for user {user_id}")
                return True
            else:
                logger.error(f"Failed to save profile updates for user {user_id}")
                return False
        else:
            logger.debug(f"No profiles needed autocomplete updates for user {user_id}")
            return True

    except Exception as e:
        logger.error(f"Error updating profiles with default collections for user {user_id}: {e}", exc_info=True)
        return False


def ensure_user_default_profile(user_id: str):
    """
    Ensure a user has MCP servers, LLM configurations, and a default profile.
    Bootstraps from tda_config.json if this is the user's first login.
    All configuration is stored per-user in database (user_preferences).
    tda_config.json is never modified - it's read-only bootstrap template.
    """
    from trusted_data_agent.core.config_manager import get_config_manager
    
    try:
        config_manager = get_config_manager()
        
        # Check if user already has configuration (check for profiles)
        existing_profiles = config_manager.get_profiles(user_id)
        if existing_profiles:
            logger.debug(f"User {user_id} already has {len(existing_profiles)} profiles - skipping bootstrap")
            return
        
        # First time for this user - bootstrap from tda_config.json
        logger.info(f"Bootstrapping configuration for user {user_id} from tda_config.json")
        
        # Load bootstrap template (read-only from tda_config.json)
        bootstrap_config = config_manager._load_bootstrap_template()
        
        # Get MCP servers and LLM configs from bootstrap template
        mcp_servers = bootstrap_config.get('mcp_servers', [])
        llm_configs = bootstrap_config.get('llm_configurations', [])
        
        if not mcp_servers:
            logger.warning(f"No MCP servers in tda_config.json - user {user_id} will have no MCP servers")
        
        if not llm_configs:
            logger.warning(f"No LLM configurations in tda_config.json - user {user_id} will have no LLM configs")
        
        # User's config will be bootstrapped automatically by load_config
        # which creates a deep copy from tda_config.json template
        # This ensures MCP servers and LLM configs are copied to user's database storage
        user_config = config_manager.load_config(user_id)
        
        # Verify profiles were bootstrapped
        profiles = user_config.get('profiles', [])
        logger.info(f"Bootstrapped user {user_id}: {len(mcp_servers)} MCP servers, {len(llm_configs)} LLM configs, {len(profiles)} profiles")
        
        # Create Default Collection for this user
        logger.info(f"Creating Default Collection for user {user_id}")
        _ensure_user_default_collection(user_id, mcp_servers)
        
    except Exception as e:
        logger.error(f"Failed to bootstrap configuration for user {user_id}: {e}", exc_info=True)


def ensure_user_default_collection(user_id: str):
    """
    Ensure a user has a default collection for each MCP server.
    Creates missing collections if needed.
    If created, reloads collections into APP_STATE and RAG retriever so they're immediately available.
    """
    from trusted_data_agent.core.collection_db import get_collection_db
    from trusted_data_agent.core.config_manager import get_config_manager
    from trusted_data_agent.core.config import APP_STATE

    try:
        config_manager = get_config_manager()

        # Get user's MCP servers from config
        mcp_servers = config_manager.get_mcp_servers(user_id)

        if not mcp_servers:
            logger.debug(f"No MCP servers configured for user {user_id}, skipping default collection check")
            return

        # Call the internal function that handles per-server collection creation
        _ensure_user_default_collection(user_id, mcp_servers)

    except Exception as e:
        logger.error(f"Failed to ensure default collections for user {user_id}: {e}", exc_info=True)


def log_audit_event(user_id: str, action: str, details: str, success: bool = True):
    """Helper to log audit events"""
    try:
        context = get_request_context()
        with get_db_session() as session:
            audit_log = AuditLog(
                user_id=user_id,
                action=action,
                details=details,
                ip_address=context['ip_address'],
                user_agent=context['user_agent'],
                status='success' if success else 'failure'
            )
            session.add(audit_log)
            session.commit()
    except Exception as e:
        logger.error(f"Failed to log audit event: {e}", exc_info=True)


@auth_bp.route('/register', methods=['POST'])
async def register():
    """
    Register a new user account with email verification.
    
    Request Body:
        {
            "username": "john_doe",
            "email": "john@example.com",
            "password": "SecurePass123!",
            "display_name": "John Doe"  // optional
        }
    
    Response:
        201: User created successfully, verification email sent
        400: Validation errors
        409: Username or email already exists
        429: Rate limit exceeded
        500: Server error
    """
    try:
        # Check rate limit
        allowed, retry_after = check_ip_register_limit()
        if not allowed:
            log_rate_limit_exceeded('ip:' + request.remote_addr, '/api/v1/auth/register')
            return jsonify({
                'status': 'error',
                'message': 'Registration rate limit exceeded',
                'retry_after': retry_after
            }), 429
        
        data = await request.get_json()
        
        # Extract fields
        username = sanitize_user_input(data.get('username', ''), max_length=30)
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        display_name = sanitize_user_input(data.get('display_name', ''), max_length=100)
        
        # Validate all fields
        is_valid, errors = validate_registration_data(username, email, password)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': 'Validation failed',
                'errors': errors
            }), 400
        
        # Hash password
        password_hash = hash_password(password)
        
        # Create user in database
        try:
            with get_db_session() as session:
                # Check for existing user
                existing_user = session.query(User).filter(
                    (User.username == username) | (User.email == email)
                ).first()
                
                if existing_user:
                    if existing_user.username == username:
                        return jsonify({
                            'status': 'error',
                            'message': 'Username already taken'
                        }), 409
                    else:
                        return jsonify({
                            'status': 'error',
                            'message': 'Email already registered'
                        }), 409
                
                # Create new user (email_verified=False by default)
                user = User(
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    display_name=display_name or username,
                    email_verified=False
                )
                
                session.add(user)
                session.commit()
                session.refresh(user)
                
                user_id = user.id
                user_uuid = user.id
                user_username = user.username
        
        except IntegrityError as e:
            logger.error(f"Database integrity error during registration: {e}")
            return jsonify({
                'status': 'error',
                'message': 'Registration failed. Please try again.'
            }), 500
        
        # Generate email verification token
        try:
            verification_token = EmailVerificationService.generate_verification_token(
                user_id=user_id,
                email=email,
                verification_type='signup'
            )
            
            # Build verification link (adjust URL to match your frontend)
            base_url = data.get('verification_base_url', os.getenv('APP_BASE_URL', 'http://localhost:5050'))
            verification_link = f"{base_url}/verify-email?token={verification_token}&email={email}"
            
            # Send verification email
            email_sent = await EmailService.send_verification_email(
                to_email=email,
                verification_token=verification_token,
                verification_link=verification_link,
                user_name=display_name or username
            )
            
            if email_sent:
                logger.info(f"Verification email sent to {email} for user {user_username}")
            else:
                logger.warning(f"Failed to send verification email to {email}, but user was created")
        
        except Exception as e:
            logger.error(f"Error generating or sending verification email: {e}", exc_info=True)
            # User was created successfully, but verification email failed
            # This is not a critical error - user can still resend later
        
        # Log audit event
        log_audit_event(
            user_id=user_id,
            action='user_registered',
            details=f'New user {user_username} registered, verification email sent',
            success=True
        )
        
        logger.info(f"New user registered: {user_username} (uuid: {user_uuid}), awaiting email verification")
        
        # Create default profile for new user (bootstrap from tda_config.json)
        ensure_user_default_profile(user_uuid)
        
        # Create default collection for new user
        ensure_user_default_collection(user_uuid)
        
        return jsonify({
            'status': 'success',
            'message': 'User registered successfully. Please check your email to verify your account.',
            'user': {
                'id': user_id,
                'username': user_username,
                'user_uuid': user_uuid,
                'display_name': display_name or username,
                'email_verified': False
            },
            'requires_email_verification': True
        }), 201
    
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error during registration'
        }), 500


@auth_bp.route('/verify-email', methods=['POST'])
async def verify_email():
    """
    Verify a user's email address using a verification token.
    
    Request Body:
        {
            "token": "verification_token_from_email",
            "email": "user@example.com"
        }
    
    Response:
        200: Email verified successfully
        400: Missing fields
        401: Invalid or expired token
        404: User or token not found
        500: Server error
    """
    try:
        data = await request.get_json()
        
        # Extract fields
        token = data.get('token', '').strip()
        email = data.get('email', '').strip().lower()
        
        logger.info(f"Email verification request: token={token[:20]}... email={email}")
        
        if not token or not email:
            logger.warning(f"Missing email verification fields: token={bool(token)}, email={bool(email)}")
            return jsonify({
                'status': 'error',
                'message': 'Missing token or email'
            }), 400
        
        # Verify the token
        logger.debug(f"Calling EmailVerificationService.verify_email with token and email {email}")
        success, user_id = EmailVerificationService.verify_email(token, email)
        
        logger.info(f"Email verification result: success={success}, user_id={user_id}")
        
        if not success:
            logger.warning(f"Email verification failed for token={token[:20]}... email={email}")
            return jsonify({
                'status': 'error',
                'message': 'Invalid or expired verification token'
            }), 401
        
        # Mark user as email verified
        try:
            with get_db_session() as session:
                user = session.query(User).filter_by(id=user_id).first()
                
                if not user:
                    return jsonify({
                        'status': 'error',
                        'message': 'User not found'
                    }), 404
                
                user.email_verified = True
                session.commit()
                
                logger.info(f"Email verified for user {user.username} (ID: {user_id})")
        
        except Exception as e:
            logger.error(f"Error marking email as verified: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': 'Error verifying email'
            }), 500
        
        # Log audit event
        log_audit_event(
            user_id=user_id,
            action='email_verified',
            details=f'Email verified for user',
            success=True
        )
        
        return jsonify({
            'status': 'success',
            'message': 'Email verified successfully',
            'user_id': user_id
        }), 200
    
    except Exception as e:
        logger.error(f"Email verification error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error during email verification'
        }), 500


@auth_bp.route('/resend-verification-email', methods=['POST'])
async def resend_verification_email():
    """
    Resend email verification email to a user.
    
    Request Body:
        {
            "email": "user@example.com",
            "verification_base_url": "http://localhost:3000"  // optional
        }
    
    Response:
        200: Verification email resent
        400: Missing email
        404: User not found or email already verified
        429: Rate limit exceeded
        500: Server error
    """
    try:
        # Rate limit resend attempts
        allowed, retry_after = check_ip_register_limit()
        if not allowed:
            log_rate_limit_exceeded('ip:' + request.remote_addr, '/api/v1/auth/resend-verification-email')
            return jsonify({
                'status': 'error',
                'message': 'Rate limit exceeded',
                'retry_after': retry_after
            }), 429
        
        data = await request.get_json()
        
        # Extract fields
        email = data.get('email', '').strip().lower()
        verification_base_url = data.get('verification_base_url', os.getenv('APP_BASE_URL', 'http://localhost:5050'))
        
        if not email:
            return jsonify({
                'status': 'error',
                'message': 'Email is required'
            }), 400
        
        # Find user
        try:
            with get_db_session() as session:
                user = session.query(User).filter_by(email=email).first()
                
                if not user:
                    return jsonify({
                        'status': 'error',
                        'message': 'User not found'
                    }), 404
                
                if user.email_verified:
                    return jsonify({
                        'status': 'error',
                        'message': 'Email already verified'
                    }), 400
                
                user_id = user.id
                user_username = user.username
                user_display_name = user.display_name or user.username
        
        except Exception as e:
            logger.error(f"Error finding user: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': 'Error processing request'
            }), 500
        
        # Generate new verification token
        try:
            verification_token = EmailVerificationService.generate_verification_token(
                user_id=user_id,
                email=email,
                verification_type='signup'
            )
            
            # Build verification link
            verification_link = f"{verification_base_url}/verify-email?token={verification_token}&email={email}"
            
            # Send verification email
            email_sent = await EmailService.send_verification_email(
                to_email=email,
                verification_token=verification_token,
                verification_link=verification_link,
                user_name=user_display_name
            )
            
            if email_sent:
                logger.info(f"Verification email resent to {email} for user {user_username}")
            else:
                logger.warning(f"Failed to resend verification email to {email}")
                return jsonify({
                    'status': 'error',
                    'message': 'Failed to send verification email'
                }), 500
        
        except Exception as e:
            logger.error(f"Error resending verification email: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'message': 'Error sending verification email'
            }), 500
        
        return jsonify({
            'status': 'success',
            'message': 'Verification email sent successfully'
        }), 200
    
    except Exception as e:
        logger.error(f"Resend verification email error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error'
        }), 500


@auth_bp.route('/forgot-password', methods=['POST'])
async def forgot_password():
    """
    Request a password reset email.

    Request Body:
        {
            "email": "user@example.com",
            "reset_base_url": "http://localhost:5050"  // optional
        }

    Response:
        200: Reset email sent (always returns success to prevent email enumeration)
        400: Missing email
        429: Rate limit exceeded
        500: Server error
    """
    from trusted_data_agent.auth.password_reset import PasswordResetService

    try:
        # Rate limit reset attempts (use register limit to prevent abuse)
        allowed, retry_after = check_ip_register_limit()
        if not allowed:
            log_rate_limit_exceeded('ip:' + request.remote_addr, '/api/v1/auth/forgot-password')
            return jsonify({
                'status': 'error',
                'message': 'Rate limit exceeded',
                'retry_after': retry_after
            }), 429

        data = await request.get_json()

        # Extract fields
        email = data.get('email', '').strip().lower()
        reset_base_url = data.get('reset_base_url', os.getenv('APP_BASE_URL', 'http://localhost:5050'))

        if not email:
            return jsonify({
                'status': 'error',
                'message': 'Email is required'
            }), 400

        # Always return success to prevent email enumeration attacks
        # But only actually send email if user exists and is not OAuth-only
        try:
            with get_db_session() as session:
                user = session.query(User).filter_by(email=email).first()

                if user:
                    # Check if this is an OAuth-only user (no usable password)
                    # OAuth users have oauth_provider set and typically a placeholder password
                    is_oauth_only = user.oauth_provider is not None and user.password_hash in ['', 'oauth_user', None]

                    if is_oauth_only:
                        logger.info(f"Password reset requested for OAuth-only user {email}, skipping")
                        # Still return success to prevent enumeration
                    else:
                        # Generate reset token
                        reset_token = PasswordResetService.generate_reset_token(
                            user_id=user.id,
                            email=email
                        )

                        if reset_token:
                            # Build reset link
                            reset_link = f"{reset_base_url}/reset-password?token={reset_token}&email={email}"

                            # Send reset email
                            user_display_name = user.display_name or user.username
                            email_sent = await EmailService.send_password_reset_email(
                                to_email=email,
                                reset_link=reset_link,
                                user_name=user_display_name
                            )

                            if email_sent:
                                logger.info(f"Password reset email sent to {email}")
                            else:
                                logger.warning(f"Failed to send password reset email to {email}")
                else:
                    logger.info(f"Password reset requested for non-existent email {email}")

        except Exception as e:
            logger.error(f"Error processing password reset: {e}", exc_info=True)
            # Still return success to prevent enumeration

        # Always return success message
        return jsonify({
            'status': 'success',
            'message': 'If an account exists with this email, you will receive a password reset link shortly.'
        }), 200

    except Exception as e:
        logger.error(f"Forgot password error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error'
        }), 500


@auth_bp.route('/reset-password', methods=['POST'])
async def reset_password():
    """
    Reset password using a valid reset token.

    Request Body:
        {
            "token": "reset_token_from_email",
            "email": "user@example.com",
            "new_password": "NewSecurePass123!"
        }

    Response:
        200: Password reset successful
        400: Missing fields or validation error
        401: Invalid or expired token
        500: Server error
    """
    from trusted_data_agent.auth.password_reset import PasswordResetService

    try:
        data = await request.get_json()

        # Extract fields
        token = data.get('token', '').strip()
        email = data.get('email', '').strip().lower()
        new_password = data.get('new_password', '')

        if not token or not email or not new_password:
            return jsonify({
                'status': 'error',
                'message': 'Token, email, and new password are required'
            }), 400

        # Validate password strength
        if len(new_password) < 8:
            return jsonify({
                'status': 'error',
                'message': 'Password must be at least 8 characters long'
            }), 400

        # Validate the token first
        is_valid, user_id, error_message = PasswordResetService.validate_reset_token(token, email)

        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': error_message
            }), 401

        # Hash the new password
        new_password_hash = hash_password(new_password)

        # Reset the password
        success, error_message = PasswordResetService.reset_password(token, email, new_password_hash)

        if success:
            # Log the password reset
            log_audit_event_detailed(
                user_id=user_id,
                action='password_reset',
                details='Password reset via forgot password flow',
                success=True
            )

            logger.info(f"Password reset successful for user {user_id}")
            return jsonify({
                'status': 'success',
                'message': 'Password reset successful. You can now log in with your new password.'
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': error_message or 'Failed to reset password'
            }), 400

    except Exception as e:
        logger.error(f"Reset password error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error'
        }), 500


@auth_bp.route('/login', methods=['POST'])
async def login():
    """
    Authenticate user and return JWT token.
    
    Request Body:
        {
            "username": "john_doe",
            "password": "SecurePass123!"
        }
    
    Response:
        200: Login successful, returns token
        400: Missing credentials
        401: Invalid credentials or account locked
        429: Rate limit exceeded
        500: Server error
    """
    try:
        # Check rate limit
        allowed, retry_after = check_ip_login_limit()
        if not allowed:
            log_rate_limit_exceeded('ip:' + request.remote_addr, '/api/v1/auth/login')
            return jsonify({
                'status': 'error',
                'message': 'Login rate limit exceeded',
                'retry_after': retry_after
            }), 429
        
        data = await request.get_json()
        
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not username or not password:
            return jsonify({
                'status': 'error',
                'message': 'Username and password are required'
            }), 400
        
        # Load user from database
        with get_db_session() as session:
            user = session.query(User).filter_by(username=username).first()
            
            if not user:
                # Don't reveal if user exists
                logger.info(f"Login attempt with non-existent username: {username}")
                return jsonify({
                    'status': 'error',
                    'message': 'Invalid username or password'
                }), 401
            
            # Get comprehensive login status
            login_status = get_login_status(user)

            # Check if account is locked
            if login_status['is_locked']:
                minutes_remaining = login_status.get('lockout_minutes_remaining', 15)
                log_audit_event(
                    user_id=user.id,
                    action='login_failed',
                    details='Login attempt while account locked',
                    success=False
                )
                return jsonify({
                    'status': 'error',
                    'message': f'Account temporarily locked due to too many failed attempts. Try again in {minutes_remaining} minutes.',
                    'locked': True,
                    'retry_after_minutes': minutes_remaining
                }), 401

            # Check progressive delay (must wait between attempts)
            if login_status['must_wait']:
                wait_seconds = login_status['wait_seconds']
                log_audit_event(
                    user_id=user.id,
                    action='login_failed',
                    details=f'Login attempt during progressive delay ({wait_seconds}s remaining)',
                    success=False
                )
                return jsonify({
                    'status': 'error',
                    'message': f'Please wait {wait_seconds} seconds before trying again.',
                    'must_wait': True,
                    'retry_after_seconds': wait_seconds,
                    'failed_attempts': login_status['failed_attempts'],
                    'remaining_attempts': login_status['remaining_attempts']
                }), 429
            
            # Check if account is active
            if not user.is_active:
                logger.warning(f"Login attempt for inactive account: {username}")
                log_audit_event(
                    user_id=user.id,
                    action='login_failed',
                    details='Login attempt for inactive account',
                    success=False
                )
                return jsonify({
                    'status': 'error',
                    'message': 'Account is inactive. Please contact support.'
                }), 401
            
            # Check if email is verified
            if not user.email_verified and not user.is_admin:
                logger.warning(f"Login attempt for unverified email: {username}")
                log_audit_event(
                    user_id=user.id,
                    action='login_failed',
                    details='Login attempt with unverified email',
                    success=False
                )
                return jsonify({
                    'status': 'error',
                    'message': 'Email not verified. Please check your email for a verification link.',
                    'requires_email_verification': True
                }), 401
            
            # Verify password
            if not verify_password(password, user.password_hash):
                logger.info(f"Failed login attempt for user: {username}")
                record_failed_login(user)

                # Re-fetch updated login status after recording failure
                with get_db_session() as status_session:
                    updated_user = status_session.query(User).filter_by(id=user.id).first()
                    updated_status = get_login_status(updated_user) if updated_user else login_status

                log_audit_event(
                    user_id=user.id,
                    action='login_failed',
                    details=f'Invalid password (attempt {updated_status["failed_attempts"]} of {MAX_LOGIN_ATTEMPTS})',
                    success=False
                )

                # Build response with helpful feedback
                response = {
                    'status': 'error',
                    'message': 'Invalid username or password'
                }

                # Add attempt info if there have been multiple failures
                if updated_status['failed_attempts'] > 1:
                    response['failed_attempts'] = updated_status['failed_attempts']
                    response['remaining_attempts'] = updated_status['remaining_attempts']

                    # Add wait time info for next attempt
                    if updated_status['must_wait']:
                        response['retry_after_seconds'] = updated_status['wait_seconds']
                        response['message'] = f'Invalid password. Please wait {updated_status["wait_seconds"]} seconds before trying again. {updated_status["remaining_attempts"]} attempts remaining.'

                    # Check if account just got locked
                    elif updated_status['is_locked']:
                        minutes = updated_status.get('lockout_minutes_remaining', 15)
                        response['locked'] = True
                        response['retry_after_minutes'] = minutes
                        response['message'] = f'Account locked due to too many failed attempts. Try again in {minutes} minutes.'

                    elif updated_status['remaining_attempts'] <= 2:
                        response['message'] = f'Invalid password. {updated_status["remaining_attempts"]} attempts remaining before account lockout.'

                return jsonify(response), 401
            
            # Password correct - reset failed login count
            reset_failed_login_attempts(user)
            
            # Update last login
            user.last_login_at = datetime.utcnow()
            session.commit()
            
            # Generate JWT token
            context = get_request_context()
            token, _ = generate_auth_token(
                user_id=user.id,
                username=user.username,
                ip_address=context['ip_address'],
                user_agent=context['user_agent']
            )
            
            # Detach user for response
            user_id = user.id
            user_username = user.username
            user_uuid = user.id
            user_display_name = user.display_name
            user_email = user.email
            user_is_admin = user.is_admin
        
        # Log audit event
        log_audit_event(
            user_id=user_id,
            action='login_success',
            details=f'User {user_username} logged in',
            success=True
        )
        
        logger.info(f"User logged in: {user_username}")
        
        # Ensure user has a default profile (bootstrap from tda_config.json)
        ensure_user_default_profile(user_uuid)
        
        # Ensure user has a default collection
        ensure_user_default_collection(user_uuid)
        
        return jsonify({
            'status': 'success',
            'message': 'Login successful',
            'token': token,
            'user': {
                'id': user_id,
                'username': user_username,
                'user_uuid': user_uuid,
                'display_name': user_display_name,
                'email': user_email,
                'is_admin': user_is_admin
            }
        }), 200
    
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error during login'
        }), 500


@auth_bp.route('/logout', methods=['POST'])
@require_auth
async def logout(current_user):
    """
    Logout user by revoking their current token.
    
    Requires: Authorization header with Bearer token
    
    Response:
        200: Logout successful
        401: Not authenticated
        500: Server error
    """
    try:
        # Get token from header
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            
            # Revoke token
            revoke_token(token)
            
            # Log audit event
            log_audit_event(
                user_id=current_user.id,
                action='logout',
                details=f'User {current_user.username} logged out',
                success=True
            )
            
            logger.info(f"User logged out: {current_user.username}")
            
            return jsonify({
                'status': 'success',
                'message': 'Logout successful'
            }), 200
        
        return jsonify({
            'status': 'error',
            'message': 'No token to revoke'
        }), 400
    
    except Exception as e:
        logger.error(f"Logout error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error during logout'
        }), 500


@auth_bp.route('/me', methods=['GET'])
@require_auth
async def get_current_user_info(current_user):
    """
    Get current authenticated user's profile information.
    
    Requires: Authorization header with Bearer token
    
    Response:
        200: User information
        401: Not authenticated
    """
    from trusted_data_agent.auth.admin import get_user_tier
    from trusted_data_agent.core.config import APP_STATE
    
    # Get license tier from APP_STATE
    license_info = APP_STATE.get('license_info') or {}
    license_tier = license_info.get('tier', 'Unknown')
    
    user_tier = get_user_tier(current_user)
    logger.debug(f"[AuthMe] User {current_user.username}: tier={user_tier}, is_admin={current_user.is_admin}")
    
    return jsonify({
        'status': 'success',
        'user': {
            'id': current_user.id,
            'username': current_user.username,
            'user_uuid': current_user.id,
            'display_name': current_user.display_name,
            'full_name': current_user.full_name,
            'email': current_user.email,
            'email_verified': current_user.email_verified,
            'is_admin': current_user.is_admin,
            'profile_tier': user_tier,
            'license_tier': license_tier,
            'is_active': current_user.is_active,
            'oauth_provider': current_user.oauth_provider,
            'marketplace_visible': current_user.marketplace_visible,
            'created_at': current_user.created_at.isoformat(),
            'last_login_at': current_user.last_login_at.isoformat() if current_user.last_login_at else None
        }
    }), 200


@auth_bp.route('/me', methods=['PUT'])
@require_auth
async def update_current_user_profile(current_user):
    """
    Update current user's profile (display_name, full_name, marketplace_visible).

    Requires: Authorization header with Bearer token

    Request Body:
        {
            "display_name": "New Name",
            "full_name": "Full Name",
            "marketplace_visible": true
        }

    Response:
        200: Updated user information
        400: Validation error
        401: Not authenticated
    """
    data = await request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'}), 400

    allowed_fields = ['display_name', 'full_name', 'marketplace_visible']
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({'status': 'error', 'message': 'No valid fields to update'}), 400

    # Validate string fields
    if 'display_name' in updates:
        val = updates['display_name']
        if val is not None and len(str(val)) > 100:
            return jsonify({'status': 'error', 'message': 'Display name too long (max 100 characters)'}), 400
    if 'full_name' in updates:
        val = updates['full_name']
        if val is not None and len(str(val)) > 255:
            return jsonify({'status': 'error', 'message': 'Full name too long (max 255 characters)'}), 400
    if 'marketplace_visible' in updates:
        if not isinstance(updates['marketplace_visible'], bool):
            return jsonify({'status': 'error', 'message': 'marketplace_visible must be a boolean'}), 400

    try:
        with get_db_session() as session:
            user = session.query(User).filter_by(id=current_user.id).first()
            if not user:
                return jsonify({'status': 'error', 'message': 'User not found'}), 404

            for field, value in updates.items():
                if field == 'marketplace_visible':
                    setattr(user, field, value)
                else:
                    setattr(user, field, value.strip() if value else None)

            user.updated_at = datetime.utcnow()
            session.commit()

            from trusted_data_agent.auth.admin import get_user_tier
            user_tier = get_user_tier(user)

            return jsonify({
                'status': 'success',
                'message': 'Profile updated successfully',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'full_name': user.full_name,
                    'email': user.email,
                    'profile_tier': user_tier,
                    'marketplace_visible': user.marketplace_visible,
                }
            }), 200

    except Exception as e:
        logger.error(f"Error updating user profile: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to update profile'}), 500


@auth_bp.route('/me/features', methods=['GET'])
@require_auth
async def get_user_features_endpoint(current_user):
    """
    Get all features available to the current user based on their profile tier.
    
    Requires: Authorization header with Bearer token
    
    Response:
        200: {
            "status": "success",
            "profile_tier": "developer",
            "features": ["execute_prompts", "view_own_sessions", ...],
            "feature_groups": {
                "session_management": true,
                "rag_management": true,
                ...
            },
            "feature_count": 35
        }
        401: Not authenticated
    """
    from trusted_data_agent.auth.features import (
        get_user_features,
        get_user_tier,
        FEATURE_GROUPS,
        user_has_feature_group
    )
    
    tier = get_user_tier(current_user)
    features = get_user_features(current_user)
    feature_list = sorted([f.value for f in features])
    
    # Check feature group access
    feature_groups = {}
    for group_name in FEATURE_GROUPS.keys():
        feature_groups[group_name] = user_has_feature_group(current_user, group_name)
    
    return jsonify({
        'status': 'success',
        'profile_tier': tier,
        'features': feature_list,
        'feature_groups': feature_groups,
        'feature_count': len(feature_list)
    }), 200


@auth_bp.route('/me/panes', methods=['GET'])
@require_auth
async def get_user_panes(current_user):
    """
    Get pane visibility configuration for current user based on their tier.
    
    Returns list of panes visible to the user's tier level.
    
    Requires: Authorization header with Bearer token
    
    Response:
        200: Pane configuration
        401: Not authenticated
        500: Server error
    """
    try:
        from trusted_data_agent.auth.models import PaneVisibility
        
        with get_db_session() as session:
            # Get all pane configurations
            panes = session.query(PaneVisibility).order_by(PaneVisibility.display_order).all()
            
            # If no panes exist, use defaults
            if not panes:
                # Import the initialization function
                from trusted_data_agent.api.admin_routes import initialize_default_panes
                panes = initialize_default_panes(session)
            
            panes_data = [pane.to_dict() for pane in panes]
        
        logger.debug(f"[PaneVisibility] Returning {len(panes_data)} panes for user {current_user.username} (tier: {current_user.profile_tier})")
        logger.debug(f"[PaneVisibility] Panes: {panes_data}")
        
        return jsonify({
            "status": "success",
            "panes": panes_data,
            "user_tier": current_user.profile_tier
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get panes for user: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@auth_bp.route('/refresh', methods=['POST'])
@require_auth
async def refresh_token(current_user):
    """
    Refresh JWT token (get a new one).
    
    Requires: Authorization header with Bearer token
    
    Response:
        200: New token issued
        401: Not authenticated
        500: Server error
    """
    try:
        # Revoke old token
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            old_token = auth_header[7:]
            revoke_token(old_token)
        
        # Generate new token
        context = get_request_context()
        new_token, _ = generate_auth_token(
            user_id=current_user.id,
            username=current_user.username,
            ip_address=context['ip_address'],
            user_agent=context['user_agent']
        )
        
        # Log audit event
        log_audit_event(
            user_id=current_user.id,
            action='token_refreshed',
            details=f'User {current_user.username} refreshed auth token',
            success=True
        )
        
        logger.info(f"Token refreshed for user: {current_user.username}")
        
        return jsonify({
            'status': 'success',
            'message': 'Token refreshed successfully',
            'token': new_token
        }), 200
    
    except Exception as e:
        logger.error(f"Token refresh error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error during token refresh'
        }), 500


@auth_bp.route('/change-password', methods=['POST'])
@require_auth
async def change_password(current_user):
    """
    Change user's password.
    
    Request Body:
        {
            "current_password": "OldPass123!",
            "new_password": "NewPass456!"
        }
    
    Requires: Authorization header with Bearer token
    
    Response:
        200: Password changed successfully
        400: Validation errors
        401: Current password incorrect
        500: Server error
    """
    try:
        data = await request.get_json()
        
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        
        if not current_password or not new_password:
            return jsonify({
                'status': 'error',
                'message': 'Current password and new password are required'
            }), 400
        
        # Verify current password
        with get_db_session() as session:
            user = session.query(User).filter_by(id=current_user.id).first()
            
            if not verify_password(current_password, user.password_hash):
                log_audit_event(
                    user_id=current_user.id,
                    action='password_change_failed',
                    details='Incorrect current password',
                    success=False
                )
                return jsonify({
                    'status': 'error',
                    'message': 'Current password is incorrect'
                }), 401
            
            # Validate new password strength
            from trusted_data_agent.auth.security import validate_password_strength
            is_valid, errors = validate_password_strength(new_password)
            if not is_valid:
                return jsonify({
                    'status': 'error',
                    'message': 'New password does not meet requirements',
                    'errors': errors
                }), 400
            
            # Hash and update password
            user.password_hash = hash_password(new_password)
            session.commit()
        
        # Log audit event
        log_audit_event(
            user_id=current_user.id,
            action='password_changed',
            details=f'User {current_user.username} changed password',
            success=True
        )
        
        logger.info(f"Password changed for user: {current_user.username}")
        
        return jsonify({
            'status': 'success',
            'message': 'Password changed successfully'
        }), 200
    
    except Exception as e:
        logger.error(f"Password change error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error during password change'
        }), 500


# Admin-only endpoint example
@auth_bp.route('/admin/users', methods=['GET'])
@require_admin
async def list_users(current_user):
    """
    List all users (admin only).
    
    Requires: Authorization header with Bearer token (admin user)
    
    Response:
        200: List of users
        401: Not authenticated
        403: Not authorized (not admin)
    """
    try:
        with get_db_session() as session:
            users = session.query(User).all()
            
            user_list = [
                {
                    'id': user.id,
                    'username': user.username,
                    'user_uuid': user.id,
                    'email': user.email,
                    'display_name': user.display_name,
                    'is_admin': user.is_admin,
                    'is_active': user.is_active,
                    'created_at': user.created_at.isoformat(),
                    'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None
                }
                for user in users
            ]
        
        return jsonify({
            'status': 'success',
            'users': user_list,
            'total': len(user_list)
        }), 200
    
    except Exception as e:
        logger.error(f"List users error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Server error listing users'
        }), 500


# ============================================================================
# Access Token Management Endpoints
# ============================================================================

@auth_bp.route("/tokens", methods=["POST"])
async def create_access_token():
    """
    Create a new access token for REST API authentication.
    
    Request body:
    {
        "name": "My API Token",
        "expires_in_days": 90  // optional, null = never expires
    }
    
    Returns:
    {
        "status": "success",
        "token": "tda_xxxxxxxx...",  // ONLY shown once!
        "token_id": "uuid",
        "name": "My API Token",
        "created_at": "2025-11-25T...",
        "expires_at": "2026-02-25T..." // or null
    }
    """
    from trusted_data_agent.auth.middleware import require_auth
    from trusted_data_agent.auth.security import create_access_token as create_token
    
    # Require authentication
    current_user = get_current_user()
    
    if not current_user:
        return jsonify({
            'status': 'error',
            'message': 'Authentication required'
        }), 401
    
    try:
        data = await request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Request body required'
            }), 400
        
        name = data.get('name', '').strip()
        expires_in_days = data.get('expires_in_days')
        
        if not name:
            return jsonify({
                'status': 'error',
                'message': 'Token name is required'
            }), 400
        
        if len(name) > 100:
            return jsonify({
                'status': 'error',
                'message': 'Token name must be 100 characters or less'
            }), 400
        
        # Validate expiration
        if expires_in_days is not None:
            if not isinstance(expires_in_days, int) or expires_in_days < 1:
                return jsonify({
                    'status': 'error',
                    'message': 'expires_in_days must be a positive integer'
                }), 400
        
        # Create token
        token_id, token = create_token(current_user.id, name, expires_in_days)
        
        # Get token details
        from trusted_data_agent.auth.models import AccessToken
        with get_db_session() as session:
            access_token = session.query(AccessToken).filter_by(id=token_id).first()
            token_data = access_token.to_dict()
        
        logger.info(f"User {current_user.username} created access token '{name}'")
        
        return jsonify({
            'status': 'success',
            'token': token,  # Full token - ONLY shown once!
            'token_id': token_id,
            'name': name,
            'token_prefix': token_data['token_prefix'],
            'created_at': token_data['created_at'],
            'expires_at': token_data['expires_at']
        }), 201
    
    except Exception as e:
        logger.error(f"Create access token error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to create access token'
        }), 500


@auth_bp.route("/tokens", methods=["GET"])
async def list_access_tokens():
    """
    List all access tokens for the authenticated user.
    
    Query parameters:
    - include_revoked: true/false (default: false)
    
    Returns:
    {
        "status": "success",
        "tokens": [
            {
                "id": "uuid",
                "name": "My Token",
                "token_prefix": "tda_abc12...",
                "created_at": "...",
                "last_used_at": "...",
                "expires_at": "..." or null,
                "revoked": false,
                "use_count": 42
            }
        ]
    }
    """
    from trusted_data_agent.auth.security import list_access_tokens as list_tokens
    
    current_user = get_current_user()
    
    if not current_user:
        return jsonify({
            'status': 'error',
            'message': 'Authentication required'
        }), 401
    
    try:
        include_revoked = request.args.get('include_revoked', 'false').lower() == 'true'
        
        tokens = list_tokens(current_user.id, include_revoked=include_revoked)
        
        return jsonify({
            'status': 'success',
            'tokens': tokens
        }), 200
    
    except Exception as e:
        logger.error(f"List access tokens error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to list access tokens'
        }), 500


@auth_bp.route("/tokens/<token_id>", methods=["DELETE"])
async def revoke_access_token(token_id: str):
    """
    Revoke an access token.
    
    Path parameter:
    - token_id: UUID of the token to revoke
    
    Returns:
    {
        "status": "success",
        "message": "Token revoked successfully"
    }
    """
    from trusted_data_agent.auth.security import revoke_access_token as revoke_token
    
    current_user = get_current_user()
    
    if not current_user:
        return jsonify({
            'status': 'error',
            'message': 'Authentication required'
        }), 401
    
    try:
        success = revoke_token(token_id, current_user.id)
        
        if not success:
            return jsonify({
                'status': 'error',
                'message': 'Token not found or already revoked'
            }), 404
        
        logger.info(f"User {current_user.username} revoked access token {token_id}")
        
        return jsonify({
            'status': 'success',
            'message': 'Token revoked successfully'
        }), 200
    
    except Exception as e:
        logger.error(f"Revoke access token error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to revoke access token'
        }), 500


@auth_bp.route('/admin/rate-limit-settings', methods=['GET'])
@require_admin
async def get_rate_limit_settings(current_user):
    """
    Get current rate limiting configuration settings.
    
    Admin only endpoint.
    
    Returns:
        200: Rate limiting settings
        401: Unauthorized
        403: Forbidden (not admin)
        500: Server error
    """
    from trusted_data_agent.auth.models import SystemSettings
    
    try:
        with get_db_session() as session:
            # Fetch all rate limit related settings
            rate_limit_keys = [
                'rate_limit_enabled',
                'rate_limit_global_override',
                'rate_limit_user_prompts_per_hour',
                'rate_limit_user_prompts_per_day',
                'rate_limit_user_configs_per_hour',
                'rate_limit_ip_login_per_minute',
                'rate_limit_ip_register_per_hour',
                'rate_limit_ip_api_per_minute'
            ]
            
            settings = {}
            for key in rate_limit_keys:
                setting = session.query(SystemSettings).filter_by(setting_key=key).first()
                if setting:
                    settings[key] = {
                        'value': setting.setting_value,
                        'description': setting.description
                    }
            
            return jsonify({
                'status': 'success',
                'settings': settings
            }), 200
    
    except Exception as e:
        logger.error(f"Get rate limit settings error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve rate limit settings'
        }), 500


@auth_bp.route('/admin/rate-limit-settings', methods=['PUT'])
@require_admin
async def update_rate_limit_settings(current_user):
    """
    Update rate limiting configuration settings.
    
    Admin only endpoint.
    
    Request Body:
        {
            "rate_limit_enabled": "true",
            "rate_limit_user_prompts_per_hour": "100",
            ...
        }
    
    Returns:
        200: Settings updated successfully
        400: Invalid request
        401: Unauthorized
        403: Forbidden (not admin)
        500: Server error
    """
    from trusted_data_agent.auth.models import SystemSettings
    
    try:
        data = await request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No settings provided'
            }), 400
        
        # Valid setting keys
        valid_keys = {
            'rate_limit_enabled',
            'rate_limit_global_override',
            'rate_limit_user_prompts_per_hour',
            'rate_limit_user_prompts_per_day',
            'rate_limit_user_configs_per_hour',
            'rate_limit_ip_login_per_minute',
            'rate_limit_ip_register_per_hour',
            'rate_limit_ip_api_per_minute'
        }
        
        # Validate input
        invalid_keys = set(data.keys()) - valid_keys
        if invalid_keys:
            return jsonify({
                'status': 'error',
                'message': f'Invalid setting keys: {", ".join(invalid_keys)}'
            }), 400
        
        with get_db_session() as session:
            updated_settings = []
            
            for key, value in data.items():
                # Convert value to string
                value_str = str(value).lower() if key in ('rate_limit_enabled', 'rate_limit_global_override') else str(value)
                
                # Validate boolean flags
                if key in ('rate_limit_enabled', 'rate_limit_global_override') and value_str not in ('true', 'false'):
                    return jsonify({
                        'status': 'error',
                        'message': f'Invalid value for {key}: must be true or false'
                    }), 400
                
                # Validate integer for numeric settings
                if key not in ('rate_limit_enabled', 'rate_limit_global_override'):
                    try:
                        int_value = int(value_str)
                        if int_value < 0:
                            return jsonify({
                                'status': 'error',
                                'message': f'Invalid value for {key}: must be non-negative integer'
                            }), 400
                    except ValueError:
                        return jsonify({
                            'status': 'error',
                            'message': f'Invalid value for {key}: must be an integer'
                        }), 400
                
                # Update or create setting
                setting = session.query(SystemSettings).filter_by(setting_key=key).first()
                if setting:
                    setting.setting_value = value_str
                    setting.updated_at = datetime.now()
                else:
                    # Create new setting if it doesn't exist
                    setting = SystemSettings(
                        setting_key=key,
                        setting_value=value_str,
                        description=f'Rate limiting setting: {key}'
                    )
                    session.add(setting)
                
                updated_settings.append(key)
            
            session.commit()
            
            # Log the configuration change
            log_audit_event_detailed(
                user_id=current_user.id,
                action='update_rate_limit_settings',
                resource='system_settings',
                success=True,
                details=f'Updated settings: {", ".join(updated_settings)}'
            )
            
            logger.info(f"User {current_user.username} updated rate limit settings: {updated_settings}")
            
            return jsonify({
                'status': 'success',
                'message': 'Rate limit settings updated successfully',
                'updated_settings': updated_settings
            }), 200
    
    except Exception as e:
        logger.error(f"Update rate limit settings error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to update rate limit settings'
        }), 500


# ============================================================================
# CONSUMPTION PROFILE MANAGEMENT
# ============================================================================

@auth_bp.route('/admin/consumption-profiles', methods=['GET'])
@require_admin
async def get_consumption_profiles(current_user):
    """
    Get all consumption profiles.
    
    Admin only endpoint.
    
    Returns:
        200: List of consumption profiles
        401: Unauthorized
        403: Forbidden (not admin)
        500: Server error
    """
    from trusted_data_agent.auth.models import ConsumptionProfile
    
    try:
        with get_db_session() as session:
            profiles = session.query(ConsumptionProfile).order_by(
                ConsumptionProfile.is_default.desc(),
                ConsumptionProfile.name
            ).all()
            
            return jsonify({
                'status': 'success',
                'profiles': [profile.to_dict() for profile in profiles]
            }), 200
    
    except Exception as e:
        logger.error(f"Get consumption profiles error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to fetch consumption profiles'
        }), 500


@auth_bp.route('/admin/consumption-profiles', methods=['POST'])
@require_admin
async def create_consumption_profile(current_user):
    """
    Create a new consumption profile.
    
    Admin only endpoint.
    
    Request Body:
        {
            "name": "Pro Tier",
            "description": "Professional tier with higher limits",
            "prompts_per_hour": 200,
            "prompts_per_day": 2000,
            "config_changes_per_hour": 20,
            "input_tokens_per_month": 500000,
            "output_tokens_per_month": 250000,
            "is_default": false
        }
    
    Returns:
        201: Profile created successfully
        400: Invalid request data
        401: Unauthorized
        403: Forbidden (not admin)
        409: Profile name already exists
        500: Server error
    """
    from trusted_data_agent.auth.models import ConsumptionProfile
    
    try:
        data = await request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No data provided'
            }), 400
        
        # Validate required fields
        name = data.get('name', '').strip()
        if not name:
            return jsonify({
                'status': 'error',
                'message': 'Profile name is required'
            }), 400
        
        with get_db_session() as session:
            # Check if name already exists
            existing = session.query(ConsumptionProfile).filter_by(name=name).first()
            if existing:
                return jsonify({
                    'status': 'error',
                    'message': f'Profile with name "{name}" already exists'
                }), 409
            
            # If this is to be the default, unset other defaults
            is_default = data.get('is_default', False)
            if is_default:
                session.query(ConsumptionProfile).update({'is_default': False})
            
            # Create new profile
            profile = ConsumptionProfile(
                name=name,
                description=data.get('description'),
                prompts_per_hour=data.get('prompts_per_hour', 100),
                prompts_per_day=data.get('prompts_per_day', 1000),
                config_changes_per_hour=data.get('config_changes_per_hour', 10),
                input_tokens_per_month=data.get('input_tokens_per_month'),
                output_tokens_per_month=data.get('output_tokens_per_month'),
                is_default=is_default,
                is_active=data.get('is_active', True)
            )
            
            session.add(profile)
            session.commit()
            session.refresh(profile)
            
            log_audit_event_detailed(
                user_id=current_user.id,
                action='create_consumption_profile',
                resource='consumption_profiles',
                success=True,
                details=f'Created profile: {name}'
            )
            
            logger.info(f"Admin {current_user.username} created consumption profile: {name}")
            
            return jsonify({
                'status': 'success',
                'message': 'Consumption profile created successfully',
                'profile': profile.to_dict()
            }), 201
    
    except Exception as e:
        logger.error(f"Create consumption profile error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to create consumption profile'
        }), 500


@auth_bp.route('/admin/consumption-profiles/<int:profile_id>', methods=['PUT'])
@require_admin
async def update_consumption_profile(current_user, profile_id: int):
    """
    Update an existing consumption profile.
    
    Admin only endpoint.
    
    Returns:
        200: Profile updated successfully
        400: Invalid request data
        401: Unauthorized
        403: Forbidden (not admin)
        404: Profile not found
        500: Server error
    """
    from trusted_data_agent.auth.models import ConsumptionProfile
    
    try:
        data = await request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No data provided'
            }), 400
        
        with get_db_session() as session:
            profile = session.query(ConsumptionProfile).filter_by(id=profile_id).first()
            
            if not profile:
                return jsonify({
                    'status': 'error',
                    'message': 'Consumption profile not found'
                }), 404
            
            # If setting as default, unset other defaults
            if data.get('is_default') and not profile.is_default:
                session.query(ConsumptionProfile).filter(
                    ConsumptionProfile.id != profile_id
                ).update({'is_default': False})
            
            # Update fields
            if 'name' in data:
                new_name = data['name'].strip()
                if new_name != profile.name:
                    # Check for name conflicts
                    existing = session.query(ConsumptionProfile).filter(
                        ConsumptionProfile.name == new_name,
                        ConsumptionProfile.id != profile_id
                    ).first()
                    if existing:
                        return jsonify({
                            'status': 'error',
                            'message': f'Profile with name "{new_name}" already exists'
                        }), 409
                    profile.name = new_name
            
            if 'description' in data:
                profile.description = data['description']
            if 'prompts_per_hour' in data:
                profile.prompts_per_hour = int(data['prompts_per_hour'])
            if 'prompts_per_day' in data:
                profile.prompts_per_day = int(data['prompts_per_day'])
            if 'config_changes_per_hour' in data:
                profile.config_changes_per_hour = int(data['config_changes_per_hour'])
            if 'input_tokens_per_month' in data:
                profile.input_tokens_per_month = data['input_tokens_per_month']
            if 'output_tokens_per_month' in data:
                profile.output_tokens_per_month = data['output_tokens_per_month']
            if 'is_default' in data:
                profile.is_default = bool(data['is_default'])
            if 'is_active' in data:
                profile.is_active = bool(data['is_active'])
            
            session.commit()
            session.refresh(profile)
            
            log_audit_event_detailed(
                user_id=current_user.id,
                action='update_consumption_profile',
                resource='consumption_profiles',
                success=True,
                details=f'Updated profile: {profile.name}'
            )
            
            logger.info(f"Admin {current_user.username} updated consumption profile: {profile.name}")
            
            return jsonify({
                'status': 'success',
                'message': 'Consumption profile updated successfully',
                'profile': profile.to_dict()
            }), 200
    
    except Exception as e:
        logger.error(f"Update consumption profile error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to update consumption profile'
        }), 500


@auth_bp.route('/admin/consumption-profiles/<int:profile_id>', methods=['DELETE'])
@require_admin
async def delete_consumption_profile(current_user, profile_id: int):
    """
    Delete a consumption profile.
    
    Admin only endpoint.
    Cannot delete if users are assigned to it.
    
    Returns:
        200: Profile deleted successfully
        400: Cannot delete (users assigned)
        401: Unauthorized
        403: Forbidden (not admin)
        404: Profile not found
        500: Server error
    """
    from trusted_data_agent.auth.models import ConsumptionProfile
    
    try:
        with get_db_session() as session:
            profile = session.query(ConsumptionProfile).filter_by(id=profile_id).first()
            
            if not profile:
                return jsonify({
                    'status': 'error',
                    'message': 'Consumption profile not found'
                }), 404
            
            # Check if any users are assigned to this profile
            user_count = len(profile.users) if profile.users else 0
            if user_count > 0:
                return jsonify({
                    'status': 'error',
                    'message': f'Cannot delete profile. {user_count} user(s) are assigned to it.',
                    'user_count': user_count
                }), 400
            
            profile_name = profile.name
            session.delete(profile)
            session.commit()
            
            log_audit_event_detailed(
                user_id=current_user.id,
                action='delete_consumption_profile',
                resource='consumption_profiles',
                success=True,
                details=f'Deleted profile: {profile_name}'
            )
            
            logger.info(f"Admin {current_user.username} deleted consumption profile: {profile_name}")
            
            return jsonify({
                'status': 'success',
                'message': 'Consumption profile deleted successfully'
            }), 200
    
    except Exception as e:
        logger.error(f"Delete consumption profile error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to delete consumption profile'
        }), 500


@auth_bp.route('/admin/users/<user_id>/consumption-profile', methods=['PUT'])
@require_admin
async def assign_user_consumption_profile(current_user, user_id: str):
    """
    Assign a consumption profile to a user.
    
    Admin only endpoint.
    
    Request Body:
        {
            "profile_id": 1  # or null to unassign
        }
    
    Returns:
        200: Profile assigned successfully
        400: Invalid request data
        401: Unauthorized
        403: Forbidden (not admin)
        404: User or profile not found
        500: Server error
    """
    from trusted_data_agent.auth.models import ConsumptionProfile
    
    try:
        data = await request.get_json()
        
        if not data or 'profile_id' not in data:
            return jsonify({
                'status': 'error',
                'message': 'profile_id is required'
            }), 400
        
        profile_id = data['profile_id']
        
        with get_db_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            
            if not user:
                return jsonify({
                    'status': 'error',
                    'message': 'User not found'
                }), 404
            
            # If profile_id is null, unassign profile
            if profile_id is None:
                user.consumption_profile_id = None
                action_desc = 'unassigned'
            else:
                # Verify profile exists
                profile = session.query(ConsumptionProfile).filter_by(
                    id=profile_id,
                    is_active=True
                ).first()
                
                if not profile:
                    return jsonify({
                        'status': 'error',
                        'message': 'Consumption profile not found or inactive'
                    }), 404
                
                user.consumption_profile_id = profile_id
                action_desc = f'assigned to {profile.name}'
            
            session.commit()
            session.refresh(user)
            
            log_audit_event_detailed(
                user_id=current_user.id,
                action='assign_consumption_profile',
                resource='users',
                success=True,
                details=f'User {user.username} {action_desc}'
            )
            
            logger.info(f"Admin {current_user.username} {action_desc} consumption profile for user {user.username}")
            
            return jsonify({
                'status': 'success',
                'message': f'Consumption profile {action_desc} successfully',
                'user': user.to_dict()
            }), 200
    
    except Exception as e:
        logger.error(f"Assign consumption profile error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to assign consumption profile'
        }), 500


@auth_bp.route('/user/quota-status', methods=['GET'])
@require_auth
async def get_user_quota_status(current_user):
    """
    Get current user's quota status and usage.
    
    Authenticated endpoint.
    
    Returns:
        200: Quota status information
        401: Unauthorized
        500: Server error
    """
    from trusted_data_agent.auth.token_quota import get_user_quota_status
    
    try:
        quota_status = get_user_quota_status(current_user.id)
        
        return jsonify({
            'status': 'success',
            'quota': quota_status
        }), 200
    
    except Exception as e:
        logger.error(f"Get quota status error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to fetch quota status'
        }), 500


@auth_bp.route('/user/consumption-summary', methods=['GET'])
@require_auth
async def get_all_users_consumption_summary(current_user):
    """
    Get consumption summary for all users from session files (admin-only).
    Aggregates tokens by user and period from actual session data.
    
    Query Parameters:
        period: Optional YYYY-MM format (defaults to current month)
    
    Returns:
        200: List of user consumption data
        403: Forbidden (non-admin)
        500: Server error
    """
    try:
        # Admin check
        if not current_user.is_admin:
            return jsonify({
                'status': 'error',
                'message': 'Admin access required'
            }), 403
        
        from pathlib import Path
        from datetime import datetime, timezone
        from collections import defaultdict
        import json
        
        # Get period parameter or use current month
        period = request.args.get('period')
        if not period:
            period = datetime.now(timezone.utc).strftime("%Y-%m")
        
        # Validate period format
        try:
            datetime.strptime(period, "%Y-%m")
        except ValueError:
            return jsonify({
                'status': 'error',
                'message': 'Invalid period format. Use YYYY-MM'
            }), 400
        
        project_root = Path(__file__).resolve().parents[3]
        sessions_base = project_root / 'tda_sessions'
        
        if not sessions_base.exists():
            return jsonify({
                'status': 'success',
                'period': period,
                'users': []
            }), 200
        
        # Aggregate tokens by user
        user_tokens = defaultdict(lambda: {'input': 0, 'output': 0})
        
        # Scan all user directories
        for user_dir in sessions_base.iterdir():
            if not user_dir.is_dir():
                continue
            
            user_id = user_dir.name
            
            # Scan session files for this user
            for session_file in user_dir.glob('*.json'):
                try:
                    with open(session_file, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                    
                    # Filter by period using created_at timestamp
                    created_at = session_data.get('created_at')
                    if created_at:
                        try:
                            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            session_period = dt.strftime("%Y-%m")
                            
                            # Only include sessions from the requested period
                            if session_period == period:
                                input_tokens = session_data.get('input_tokens', 0)
                                output_tokens = session_data.get('output_tokens', 0)
                                user_tokens[user_id]['input'] += input_tokens
                                user_tokens[user_id]['output'] += output_tokens
                        except Exception as e:
                            logger.debug(f"Could not parse created_at for session {session_file.name}: {e}")
                            continue
                
                except Exception as e:
                    logger.debug(f"Could not read session file {session_file}: {e}")
                    continue
        
        # Get user details and consumption profiles from database
        from trusted_data_agent.auth.token_quota import get_user_consumption_profile
        
        users_list = []
        
        with get_db_session() as db_session:
            for user_id, tokens in user_tokens.items():
                # Get user from database
                user = db_session.query(User).filter_by(id=user_id).first()
                if not user:
                    continue
                
                # Get consumption profile
                profile = get_user_consumption_profile(user_id)
                
                users_list.append({
                    'user_id': user_id,
                    'username': user.username,
                    'email': user.email,
                    'profile_name': profile['name'] if profile else 'No Profile',
                    'profile_id': profile['id'] if profile else None,
                    'input_tokens': tokens['input'],
                    'output_tokens': tokens['output'],
                    'total_tokens': tokens['input'] + tokens['output']
                })
        
        return jsonify({
            'status': 'success',
            'period': period,
            'users': users_list
        }), 200
    
    except Exception as e:
        logger.error(f"Get consumption summary error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to fetch consumption summary'
        }), 500


# ============================================================================
# OAuth Routes
# ============================================================================

@auth_bp.route('/oauth/providers', methods=['GET'])
async def get_oauth_providers():
    """
    Get list of available OAuth providers.
    
    Returns:
        JSON with list of configured OAuth providers
    """
    from trusted_data_agent.auth.oauth_config import get_configured_providers
    
    try:
        providers = get_configured_providers()
        provider_list = [
            {
                'name': name,
                'display_name': name.capitalize(),
                'icon': f'oauth-{name}',
                'enabled': True,
            }
            for name in providers.keys()
        ]
        
        return jsonify({
            'status': 'success',
            'providers': provider_list
        }), 200
    
    except Exception as e:
        logger.error(f"Error fetching OAuth providers: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to fetch OAuth providers'
        }), 500


@auth_bp.route('/oauth/<provider>', methods=['GET'])
async def initiate_oauth(provider):
    """
    Initiate OAuth flow by redirecting to provider authorization endpoint.
    
    Query parameters:
        return_to: Optional URL to return to after OAuth callback
    
    Returns:
        Redirect to OAuth provider authorization endpoint
    """
    from trusted_data_agent.auth.oauth_middleware import (
        OAuthAuthorizationBuilder,
        validate_oauth_provider,
        OAuthErrorHandler
    )
    
    try:
        # Validate provider
        if not validate_oauth_provider(provider):
            return jsonify({
                'status': 'error',
                'message': f'OAuth provider "{provider}" is not configured'
            }), 404
        
        # Get return_to URL if provided
        return_to = request.args.get('return_to')
        
        # Build authorization URL
        auth_url = await OAuthAuthorizationBuilder.build_authorization_url(
            provider_name=provider,
            return_to=return_to
        )
        
        if not auth_url:
            OAuthErrorHandler.log_oauth_event(provider, 'initiate', success=False, details='Failed to build auth URL')
            return jsonify({
                'status': 'error',
                'message': 'Failed to build authorization URL'
            }), 500
        
        OAuthErrorHandler.log_oauth_event(provider, 'initiate', success=True)
        
        # Redirect to OAuth provider
        from quart import redirect
        return redirect(auth_url)
    
    except Exception as e:
        logger.error(f"Error initiating OAuth for {provider}: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to initiate OAuth flow'
        }), 500


@auth_bp.route('/oauth/<provider>/callback', methods=['GET'])
async def oauth_callback(provider):
    """
    Handle OAuth callback from provider.
    
    Query parameters:
        code: Authorization code from provider
        state: State parameter for CSRF protection
        error: Error code if authorization failed
    
    Returns:
        Redirect to frontend with JWT token or error
    """
    from trusted_data_agent.auth.oauth_handlers import OAuthHandler
    from trusted_data_agent.auth.exceptions import UserDeactivatedException
    from trusted_data_agent.auth.oauth_middleware import (
        OAuthCallbackValidator,
        OAuthErrorHandler,
        get_client_ip,
        validate_oauth_provider,
        OAuthSession,
    )
    from quart import redirect
    from urllib.parse import urlencode
    
    try:
        # Validate provider
        if not validate_oauth_provider(provider):
            OAuthErrorHandler.log_oauth_event(provider, 'callback', success=False, details='Provider not configured')
            error_params = urlencode({'error': 'Provider not configured'})
            return redirect(f"/login?{error_params}")
        
        # Validate callback request
        is_valid, code, state, error_msg = await OAuthCallbackValidator.validate_callback_request(provider)

        if not is_valid:
            OAuthErrorHandler.log_oauth_event(provider, 'callback', success=False, details=error_msg)
            error_params = urlencode({'error': error_msg or 'OAuth authorization failed'})
            return redirect(f"/login?{error_params}")

        # Check if this is an account linking flow (user_id stored during initiate)
        link_user_id = session.pop(OAuthSession.LINK_USER_SESSION_KEY, None)

        if link_user_id:
            from trusted_data_agent.auth.oauth_handlers import link_oauth_to_existing_user
            callback_uri = OAuthCallbackValidator.get_callback_redirect_uri(provider)

            success, message = await link_oauth_to_existing_user(
                user_id=link_user_id,
                provider_name=provider,
                code=code,
                redirect_uri=callback_uri
            )

            return_to = '/?tab=profile&section=connected_accounts'
            if success:
                OAuthErrorHandler.log_oauth_event(provider, 'link', user_id=link_user_id, success=True)
                logger.info(f"Successfully linked {provider} to user {link_user_id}")
                separator = '&' if '?' in return_to else '?'
                return redirect(f"{return_to}{separator}link_success={provider}")
            else:
                OAuthErrorHandler.log_oauth_event(provider, 'link', user_id=link_user_id, success=False, details=message)
                logger.warning(f"Failed to link {provider} to user {link_user_id}: {message}")
                separator = '&' if '?' in return_to else '?'
                error_encoded = urlencode({'link_error': message})
                return redirect(f"{return_to}{separator}{error_encoded}")

        # Handle regular OAuth login callback
        handler = OAuthHandler(provider)
        callback_uri = OAuthCallbackValidator.get_callback_redirect_uri(provider)
        
        try:
            jwt_token, user_dict, new_user_created = await handler.handle_callback(
                code=code,
                redirect_uri=callback_uri,
                state=state
            )
        except UserDeactivatedException:
            OAuthErrorHandler.log_oauth_event(provider, 'callback', success=False, details='Attempted login by deactivated user.')
            error_params = urlencode({
                'error': 'Account Deactivated',
                'error_description': 'Your account is deactivated. For activation, please contact info@uderia.com'
            })
            return redirect(f"/login?{error_params}")

        if not jwt_token or not user_dict:
            OAuthErrorHandler.log_oauth_event(provider, 'callback', success=False, details='Failed to complete OAuth flow')
            error_params = urlencode({'error': 'Failed to complete OAuth authentication'})
            return redirect(f"/login?{error_params}")

        if new_user_created:
            user_id = user_dict.get('id')
            if user_id:
                logger.info(f"New user {user_id} created via OAuth, ensuring default profile and collection.")
                ensure_user_default_profile(user_id)
                ensure_user_default_collection(user_id)
            else:
                logger.warning("A new user was created via OAuth, but no user_id was found in the user dictionary.")

        # Get return_to URL from session
        return_to = OAuthSession.get_return_to()
        
        # Log successful OAuth login
        ip_address = await get_client_ip()
        OAuthErrorHandler.log_oauth_event(
            provider,
            'login',
            user_id=user_dict.get('id'),
            success=True,
            details=f"IP: {ip_address}"
        )
        
        logger.info(f"Successful OAuth login for user {user_dict.get('id')} via {provider}")
        
        # Redirect to frontend with JWT token
        redirect_url = return_to or '/'
        # Append token to redirect URL (frontend should handle this)
        separator = '&' if '?' in redirect_url else '?'
        redirect_url = f"{redirect_url}{separator}token={jwt_token}"
        
        return redirect(redirect_url)
    
    except Exception as e:
        logger.error(f"Error processing OAuth callback from {provider}: {e}", exc_info=True)
        OAuthErrorHandler.log_oauth_event(provider, 'callback', success=False, details=str(e))
        error_params = urlencode({'error': 'An unexpected error occurred'})
        return redirect(f"/login?{error_params}")


@auth_bp.route('/oauth/<provider>/link', methods=['GET'])
async def initiate_oauth_link(provider):
    """
    Initiate OAuth flow to link provider account to existing user.

    Authentication via query parameter (browser navigation cannot send headers).
    The JWT token is passed as ?token=<jwt> and verified manually.
    The user_id is stored in the session so the callback can retrieve it.

    Returns:
        Redirect to OAuth provider authorization endpoint
    """
    from trusted_data_agent.auth.oauth_middleware import (
        OAuthAuthorizationBuilder,
        OAuthSession,
        validate_oauth_provider,
        OAuthErrorHandler
    )
    from quart import redirect

    try:
        # Authenticate via query parameter (window.location.href can't send headers)
        token = request.args.get('token')
        if not token:
            return jsonify({
                'status': 'error',
                'message': 'Authentication required. Please login.'
            }), 401

        payload = verify_auth_token(token)
        if not payload:
            return jsonify({
                'status': 'error',
                'message': 'Invalid or expired token'
            }), 401

        user_id = payload.get('user_id')
        if not user_id:
            return jsonify({
                'status': 'error',
                'message': 'Invalid token payload'
            }), 401

        # Validate provider
        if not validate_oauth_provider(provider):
            return jsonify({
                'status': 'error',
                'message': f'OAuth provider "{provider}" is not configured'
            }), 404

        # Store user_id in session so the callback can identify who to link to
        session[OAuthSession.LINK_USER_SESSION_KEY] = user_id

        # Build authorization URL (uses the regular callback URL)
        auth_url = await OAuthAuthorizationBuilder.build_authorization_url(
            provider_name=provider,
            return_to='/?tab=profile&section=connected_accounts'
        )

        if not auth_url:
            OAuthErrorHandler.log_oauth_event(provider, 'link_initiate', user_id=user_id, success=False)
            return jsonify({
                'status': 'error',
                'message': 'Failed to build authorization URL'
            }), 500

        OAuthErrorHandler.log_oauth_event(provider, 'link_initiate', user_id=user_id, success=True)

        return redirect(auth_url)

    except Exception as e:
        logger.error(f"Error initiating OAuth link for {provider}: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to initiate OAuth linking'
        }), 500


@auth_bp.route('/oauth/<provider>/link/callback', methods=['GET'])
@require_auth
async def oauth_link_callback(provider):
    """
    Handle OAuth callback for account linking.
    
    Query parameters:
        code: Authorization code from provider
        state: State parameter for CSRF protection
    
    Returns:
        JSON response with success/error status
    """
    from trusted_data_agent.auth.oauth_handlers import link_oauth_to_existing_user
    from trusted_data_agent.auth.oauth_middleware import (
        OAuthCallbackValidator,
        OAuthErrorHandler,
        validate_oauth_provider,
    )
    
    try:
        # Validate provider
        if not validate_oauth_provider(provider):
            return jsonify({
                'status': 'error',
                'message': f'OAuth provider "{provider}" is not configured'
            }), 404
        
        # Validate callback request
        is_valid, code, state, error_msg = await OAuthCallbackValidator.validate_callback_request(provider)
        
        if not is_valid:
            OAuthErrorHandler.log_oauth_event(provider, 'link_callback', success=False, details=error_msg)
            return jsonify({
                'status': 'error',
                'message': error_msg or 'OAuth authorization failed'
            }), 400
        
        # Get current user
        current_user = await get_current_user()
        if not current_user:
            return jsonify({
                'status': 'error',
                'message': 'User not authenticated'
            }), 401
        
        # Link OAuth account
        callback_uri = OAuthCallbackValidator.get_callback_redirect_uri(provider) + '/link/callback'
        success, message = await link_oauth_to_existing_user(
            user_id=current_user['id'],
            provider_name=provider,
            code=code,
            redirect_uri=callback_uri
        )
        
        if success:
            OAuthErrorHandler.log_oauth_event(provider, 'link', user_id=current_user['id'], success=True)
            return jsonify({
                'status': 'success',
                'message': message
            }), 200
        else:
            OAuthErrorHandler.log_oauth_event(provider, 'link', user_id=current_user['id'], success=False, details=message)
            return jsonify({
                'status': 'error',
                'message': message
            }), 400
    
    except Exception as e:
        logger.error(f"Error processing OAuth link callback from {provider}: {e}", exc_info=True)
        OAuthErrorHandler.log_oauth_event(provider, 'link_callback', success=False, details=str(e))
        return jsonify({
            'status': 'error',
            'message': 'An error occurred while linking the account'
        }), 500


@auth_bp.route('/oauth/<provider>/disconnect', methods=['POST'])
@require_auth
async def disconnect_oauth(provider):
    """
    Disconnect/unlink an OAuth account from the current user.
    
    Requires authentication.
    
    Returns:
        JSON response with success/error status
    """
    from trusted_data_agent.auth.oauth_handlers import unlink_oauth_from_user
    from trusted_data_agent.auth.oauth_middleware import OAuthErrorHandler
    
    try:
        # Get current user
        current_user = await get_current_user()
        if not current_user:
            return jsonify({
                'status': 'error',
                'message': 'User not authenticated'
            }), 401
        
        # Unlink OAuth account
        success, message = await unlink_oauth_from_user(
            user_id=current_user['id'],
            provider_name=provider
        )
        
        if success:
            OAuthErrorHandler.log_oauth_event(provider, 'disconnect', user_id=current_user['id'], success=True)
            return jsonify({
                'status': 'success',
                'message': message
            }), 200
        else:
            OAuthErrorHandler.log_oauth_event(provider, 'disconnect', user_id=current_user['id'], success=False, details=message)
            return jsonify({
                'status': 'error',
                'message': message
            }), 400
    
    except Exception as e:
        logger.error(f"Error disconnecting OAuth account for {provider}: {e}", exc_info=True)
        OAuthErrorHandler.log_oauth_event(provider, 'disconnect', success=False, details=str(e))
        return jsonify({
            'status': 'error',
            'message': 'An error occurred while disconnecting the account'
        }), 500


@auth_bp.route('/oauth/accounts', methods=['GET'])
@require_auth
async def get_oauth_accounts():
    """
    Get list of OAuth accounts linked to the current user.
    
    Requires authentication.
    
    Returns:
        JSON with list of linked OAuth accounts
    """
    try:
        current_user = await get_current_user()
        if not current_user:
            return jsonify({
                'status': 'error',
                'message': 'User not authenticated'
            }), 401
        
        with get_db_session() as session:
            user = session.query(User).filter_by(id=current_user['id']).first()
            if not user:
                return jsonify({
                    'status': 'error',
                    'message': 'User not found'
                }), 404
            
            oauth_accounts = [account.to_dict() for account in user.oauth_accounts]
        
        return jsonify({
            'status': 'success',
            'accounts': oauth_accounts
        }), 200
    
    except Exception as e:
        logger.error(f"Error fetching OAuth accounts: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to fetch OAuth accounts'
        }), 500
