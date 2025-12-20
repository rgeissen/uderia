# src/trusted_data_agent/api/system_prompts_routes.py
"""
Phase 3: System Prompts API - Updated to use database backend

Previously used prompt_overrides/ files, now uses database-backed PromptLoader.
Maintains backward compatibility with existing UI.
"""

import os
import logging
from quart import Blueprint, jsonify, request
from functools import wraps

from trusted_data_agent.core.config import APP_STATE
from trusted_data_agent.auth.middleware import require_auth
from trusted_data_agent.agent.prompt_loader import get_prompt_loader
from trusted_data_agent.agent.prompt_encryption import encrypt_prompt

system_prompts_bp = Blueprint('system_prompts', __name__, url_prefix='/api/v1/system-prompts')
app_logger = logging.getLogger("quart.app")

def require_prompt_engineer_or_enterprise(f):
    """
    Decorator to require Prompt Engineer or Enterprise license tier.
    Must be used with @require_auth decorator.
    current_user is injected by @require_auth as the first parameter.
    """
    @wraps(f)
    async def decorated_function(current_user, *args, **kwargs):
        # Check license tier from PromptLoader
        loader = get_prompt_loader()
        
        if not loader.has_tier_access('Prompt Engineer'):
            license_info = APP_STATE.get('license_info') or {}
            license_tier = license_info.get('tier', 'Unknown')
            return jsonify({
                "success": False,
                "message": f"System Prompt Editor requires 'Prompt Engineer' or 'Enterprise' license tier. Current tier: {license_tier}"
            }), 403
        
        return await f(current_user, *args, **kwargs)
    
    return decorated_function


@system_prompts_bp.route('/list', methods=['GET'])
@require_auth
async def list_all_prompts(current_user):
    """
    List all available prompts from the database.
    
    Returns list of prompts with metadata (name, display_name, role, is_active, etc.)
    """
    try:
        loader = get_prompt_loader()
        prompts = loader.list_prompts()
        
        return jsonify({
            "success": True,
            "prompts": prompts,
            "total_count": len(prompts)
        })
        
    except Exception as e:
        app_logger.error(f"Error listing prompts: {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to list prompts: {str(e)}"
        }), 500


@system_prompts_bp.route('/<prompt_name>', methods=['GET'])
@require_auth
async def get_system_prompt(current_user, prompt_name):
    """
    Get the current content of a system prompt from the database.
    Returns base prompt + any overrides based on user tier.
    
    NOW: Loads from database via PromptLoader
    BEFORE: Loaded from prompt_overrides/ files or prompts.dat
    """
    try:
        loader = get_prompt_loader()
        
        # Verify prompt exists
        metadata = loader.get_prompt_metadata(prompt_name)
        if not metadata:
            # List available prompts for error message
            all_prompts = loader.list_prompts()
            available = [p['name'] for p in all_prompts]
            return jsonify({
                "success": False,
                "message": f"Invalid prompt name. Available prompts: {', '.join(available)}"
            }), 400
        
        # Get content with decryption but WITHOUT parameter resolution
        # Pass empty dict for parameters to skip substitution
        user_uuid = current_user.id
        content = loader.get_prompt(prompt_name, user_uuid=user_uuid, parameters={})
        
        # Check if this user has an override
        import sqlite3
        conn = sqlite3.connect(loader.db_path)
        cursor = conn.cursor()
        
        has_override = False
        active_version_id = None
        
        # Check for user-level override first (highest priority)
        cursor.execute("""
            SELECT id, active_version_id FROM prompt_overrides 
            WHERE prompt_id = ? AND user_uuid = ? AND is_active = 1
        """, (metadata['id'], user_uuid))
        override_row = cursor.fetchone()
        
        if override_row:
            has_override = True
            active_version_id = override_row[1]  # active_version_id column
        
        # If no user-level override, check profile-level
        if not has_override:
            cursor.execute("""
                SELECT id, active_version_id FROM prompt_overrides 
                WHERE prompt_id = ? AND profile_id IS NULL AND is_active = 1
            """, (metadata['id'],))
            profile_override_row = cursor.fetchone()
            if profile_override_row:
                has_override = True
                active_version_id = profile_override_row[1]
        
        # Get the LATEST version from prompt_versions (v1 always exists from bootstrap)
        cursor.execute("""
            SELECT MAX(version), id FROM prompt_versions WHERE prompt_id = ?
        """, (metadata['id'],))
        latest_version_row = cursor.fetchone()
        latest_version_number = None
        latest_version_id = None
        if latest_version_row and latest_version_row[0]:
            latest_version_number = latest_version_row[0]
            # Get the ID of this latest version
            cursor.execute("""
                SELECT id FROM prompt_versions 
                WHERE prompt_id = ? AND version = ?
            """, (metadata['id'], latest_version_number))
            version_id_row = cursor.fetchone()
            if version_id_row:
                latest_version_id = version_id_row[0]
        
        # Determine which version is actually being returned (active version, not necessarily latest)
        actual_version_number = latest_version_number
        if active_version_id is not None:
            # A specific version is pinned - find its version number
            cursor.execute("""
                SELECT version FROM prompt_versions WHERE id = ?
            """, (active_version_id,))
            pinned_row = cursor.fetchone()
            if pinned_row:
                actual_version_number = pinned_row[0]
        
        # Set metadata version to the actual version being returned
        metadata['version'] = actual_version_number
        
        # The GET endpoint always returns the active version content (via loader.get_prompt)
        # So is_version_active should always be True
        is_version_active = True
        
        conn.close()
        
        app_logger.info(f"GET {prompt_name}: version={metadata.get('version')}, is_override={has_override}, active_version_id={active_version_id}, is_version_active={is_version_active}")
        
        return jsonify({
            "success": True,
            "prompt_name": prompt_name,
            "content": content,
            "is_override": has_override,
            "is_version_active": is_version_active,
            "metadata": metadata
        })
        
    except Exception as e:
        app_logger.error(f"Error getting system prompt {prompt_name}: {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to load system prompt: {str(e)}"
        }), 500


@system_prompts_bp.route('/<prompt_name>', methods=['PUT'])
@require_auth
@require_prompt_engineer_or_enterprise
async def update_system_prompt(current_user, prompt_name):
    """
    Save a system prompt override to the database.
    
    Tier-based behavior:
    - Prompt Engineer: Can create profile-level overrides
    - Enterprise: Can create user-level overrides
    
    NOW: Saves to database as prompt_overrides
    BEFORE: Saved to prompt_overrides/ directory
    """
    try:
        loader = get_prompt_loader()
        
        # Verify prompt exists
        metadata = loader.get_prompt_metadata(prompt_name)
        if not metadata:
            return jsonify({
                "success": False,
                "message": f"Invalid prompt name '{prompt_name}'"
            }), 400
        
        data = await request.get_json()
        content = data.get('content', '')
        
        if not content:
            return jsonify({
                "success": False,
                "message": "Content is required"
            }), 400
        
        # Determine override scope based on tier
        import sqlite3
        license_info = APP_STATE.get('license_info') or {}
        license_tier = license_info.get('tier', 'Standard')
        user_uuid = current_user.id
        
        conn = None
        try:
            conn = sqlite3.connect(loader.db_path)
            cursor = conn.cursor()
            
            # Get prompt_id and current version
            cursor.execute("SELECT id, version FROM prompts WHERE name = ?", (prompt_name,))
            row = cursor.fetchone()
            if not row:
                return jsonify({"success": False, "message": "Prompt not found"}), 404
            
            prompt_id, current_version = row[0], row[1]
            
            # Encrypt the content before storing (content comes from UI as plain text)
            encrypted_content = encrypt_prompt(content, loader._decryption_key)
            
            # Get old override content (encrypted) for comparison
            old_override_content = None
            if license_tier == 'Enterprise':
                cursor.execute("""
                    SELECT content FROM prompt_overrides 
                    WHERE prompt_id = ? AND user_uuid = ? AND is_active = 1
                """, (prompt_id, user_uuid))
            else:
                cursor.execute("""
                    SELECT content FROM prompt_overrides 
                    WHERE prompt_id = ? AND profile_id IS NULL AND is_active = 1
                """, (prompt_id,))
            
            existing_row = cursor.fetchone()
            if existing_row:
                old_override_content = existing_row[0]
            
            # Only create version if content actually changed (compare encrypted)
            content_changed = old_override_content != encrypted_content
            
            created_version = None
            if license_tier == 'Enterprise':
                # User-level override
                cursor.execute("""
                    INSERT OR REPLACE INTO prompt_overrides 
                    (prompt_id, user_uuid, content, created_by)
                    VALUES (?, ?, ?, ?)
                """, (prompt_id, user_uuid, encrypted_content, user_uuid))
                scope = 'user'
            else:
                # Profile-level override (Prompt Engineer tier)
                cursor.execute("""
                    INSERT OR REPLACE INTO prompt_overrides 
                    (prompt_id, profile_id, content, created_by)
                    VALUES (?, NULL, ?, ?)
                """, (prompt_id, encrypted_content, user_uuid))
                scope = 'profile'
            
            # Create version history entry for override changes
            if content_changed:
                # Get the next version number (max existing + 1)
                # v1 always exists from bootstrap, so this will return at least 1
                cursor.execute("""
                    SELECT COALESCE(MAX(version), 0) FROM prompt_versions WHERE prompt_id = ?
                """, (prompt_id,))
                max_version = cursor.fetchone()[0]
                next_version = max_version + 1
                
                # Only store the NEW content in version history (not the old - it's already there)
                cursor.execute("""
                    INSERT INTO prompt_versions (prompt_id, version, content, changed_by, change_reason, created_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    prompt_id, 
                    next_version, 
                    encrypted_content,  # Store encrypted
                    user_uuid,
                    f"Override updated ({scope}-level)"
                ))
                
                created_version = next_version
                app_logger.info(f"Created version {next_version} for override of {prompt_name}")
            
            conn.commit()
            
        except sqlite3.IntegrityError as e:
            if conn:
                conn.rollback()
            app_logger.error(f"Database integrity error saving {prompt_name}: {e}")
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        except Exception as e:
            if conn:
                conn.rollback()
            app_logger.error(f"Error saving system prompt {prompt_name}: {e}")
            return jsonify({
                "success": False,
                "message": f"Failed to save system prompt: {str(e)}"
            }), 500
        finally:
            if conn:
                conn.close()
        
        # Clear cache - need to clear all cache entries for this prompt
        # Cache key format: "{name}:{user_uuid}:{profile_id}"
        # Clear all variations to ensure the new override is loaded
        keys_to_delete = [key for key in loader._prompt_cache.keys() if key.startswith(f"{prompt_name}:")]
        for key in keys_to_delete:
            del loader._prompt_cache[key]
        
        if keys_to_delete:
            app_logger.info(f"Cleared {len(keys_to_delete)} cached entries for {prompt_name}")
        
        app_logger.info(f"System prompt override saved: {prompt_name} ({scope}-level)")
        
        return jsonify({
            "success": True,
            "message": f"System prompt '{prompt_name}' saved successfully ({scope}-level override)",
            "prompt_name": prompt_name,
            "override_scope": scope,
            "version": created_version  # Return the newly created version number
        })
        
    except Exception as e:
        app_logger.error(f"Error saving system prompt {prompt_name}: {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to save system prompt: {str(e)}"
        }), 500


@system_prompts_bp.route('/<prompt_name>', methods=['DELETE'])
@require_auth
@require_prompt_engineer_or_enterprise
async def delete_system_prompt_override(current_user, prompt_name):
    """
    Delete a system prompt override, reverting to the base version.
    
    NOW: Deletes from database
    BEFORE: Deleted from prompt_overrides/ directory
    """
    try:
        loader = get_prompt_loader()
        
        # Verify prompt exists
        metadata = loader.get_prompt_metadata(prompt_name)
        if not metadata:
            return jsonify({
                "success": False,
                "message": f"Invalid prompt name '{prompt_name}'"
            }), 400
        
        import sqlite3
        user_uuid = current_user.id
        
        conn = sqlite3.connect(loader.db_path)
        cursor = conn.cursor()
        
        # Get prompt_id
        cursor.execute("SELECT id FROM prompts WHERE name = ?", (prompt_name,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "message": "Prompt not found"}), 404
        
        prompt_id = row[0]
        
        # Delete overrides for this user
        cursor.execute("""
            DELETE FROM prompt_overrides 
            WHERE prompt_id = ? AND user_uuid = ?
        """, (prompt_id, user_uuid))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        # Clear cache - need to clear all cache entries for this prompt
        keys_to_delete = [key for key in loader._prompt_cache.keys() if key.startswith(f"{prompt_name}:")]
        for key in keys_to_delete:
            del loader._prompt_cache[key]
        
        if keys_to_delete:
            app_logger.info(f"Cleared {len(keys_to_delete)} cached entries for {prompt_name}")
        
        if deleted == 0:
            return jsonify({
                "success": True,
                "message": f"No override exists for '{prompt_name}', already using base version"
            })
        
        app_logger.info(f"System prompt override deleted: {prompt_name}")
        
        return jsonify({
            "success": True,
            "message": f"System prompt override deleted, reverted to base version for '{prompt_name}'"
        })
        
    except Exception as e:
        app_logger.error(f"Error deleting system prompt override {prompt_name}: {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to delete system prompt override: {str(e)}"
        }), 500


@system_prompts_bp.route('/list', methods=['GET'])
@require_auth
async def list_system_prompts(current_user):
    """
    List all available system prompts with their override status.
    Available to all tiers (viewing), but editing requires Prompt Engineer+.
    
    NOW: Loads from database
    BEFORE: Listed files in prompt_overrides/ directory
    """
    try:
        loader = get_prompt_loader()
        user_uuid = current_user.id
        
        # Get all prompts
        all_prompts = loader.list_prompts()
        
        import sqlite3
        conn = sqlite3.connect(loader.db_path)
        cursor = conn.cursor()
        
        # Check for overrides for each prompt
        prompts_with_status = []
        for prompt in all_prompts:
            # Check if this user has any overrides
            cursor.execute("""
                SELECT COUNT(*) FROM prompt_overrides po
                JOIN prompts p ON po.prompt_id = p.id
                WHERE p.name = ? AND (po.user_id = ? OR po.profile_id IN (
                    SELECT profile_id FROM profile_prompt_assignments WHERE user_id = ?
                ))
            """, (prompt['name'], user_uuid, user_uuid))
            
            has_override = cursor.fetchone()[0] > 0
            
            prompts_with_status.append({
                "name": prompt['name'],
                "display_name": prompt['display_name'],
                "description": prompt.get('description'),
                "category": prompt.get('category'),
                "role": prompt['role'],
                "version": prompt['version'],
                "has_override": has_override,
                "is_active": prompt['is_active']
            })
        
        conn.close()
        
        # Get license info for UI
        license_info = APP_STATE.get('license_info') or {}
        can_edit = loader.has_tier_access('Prompt Engineer')
        
        return jsonify({
            "success": True,
            "prompts": prompts_with_status,
            "total_count": len(prompts_with_status),
            "can_edit": can_edit,
            "license_tier": license_info.get('tier', 'Standard')
        })
        
    except Exception as e:
        app_logger.error(f"Error listing system prompts: {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to list system prompts: {str(e)}"
        }), 500


# ============================================================================
# PHASE 4: Enhanced Features
# ============================================================================

@system_prompts_bp.route('/<prompt_name>/parameters', methods=['GET'])
@require_auth
async def get_prompt_parameters(current_user, prompt_name):
    """
    Get parameters for a specific prompt (global + prompt-specific).
    Only shows parameters that are actually referenced in the prompt content.
    Phase 4: Parameter viewer
    """
    try:
        loader = get_prompt_loader()
        user_uuid = current_user.id
        
        # Verify prompt exists
        metadata = loader.get_prompt_metadata(prompt_name)
        if not metadata:
            return jsonify({
                "success": False,
                "message": f"Prompt '{prompt_name}' not found"
            }), 404
        
        import sqlite3
        import re
        conn = sqlite3.connect(loader.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get the RAW prompt content WITHOUT parameter resolution
        # We need to see the {parameter_name} placeholders, not the resolved values
        # Use loader to decrypt but pass empty parameters dict to skip substitution
        prompt_content = loader.get_prompt(prompt_name, user_uuid=user_uuid, parameters={})
        
        # Debug logging
        app_logger.info(f"Extracting parameters from {prompt_name}, content length: {len(prompt_content) if prompt_content else 0}")
        app_logger.debug(f"Content preview: {prompt_content[:200] if prompt_content else 'None'}")
        
        # Extract parameter names from prompt content using regex
        # Matches {parameter_name} patterns
        parameter_pattern = r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}'
        all_referenced = set(re.findall(parameter_pattern, prompt_content))
        app_logger.info(f"Found parameters in {prompt_name}: {all_referenced}")
        
        # Filter out dynamic/runtime parameters (sections, contexts, runtime values)
        # These are typically injected at runtime and not stored as global parameters
        excluded_suffixes = ('_section', '_context', '_history', '_info', '_data', '_message', 
                            '_goal', '_plan', '_depth', '_description', '_arguments', '_definition',
                            '_command', '_queries',
                            '_question', '_input', '_action', '_examples', '_rule',
                            '_instructions', '_details', '_tool_name', '_table_name', '_column_name')
        
        # Additional runtime-specific exact matches (not suffixes)
        # These are specific runtime variables, NOT configurable parameters
        excluded_patterns = ('tool_name', 'table_name', 'column_name', 'database_name', 'schema_name',
                            'invalid_table_name', 'invalid_column_name', 'failed_arguments', 'user_question')
        
        referenced_params = {
            param for param in all_referenced 
            if not any(param.endswith(suffix) for suffix in excluded_suffixes)
            and param not in excluded_patterns
        }
        
        # Get global parameters (only those referenced in prompt)
        cursor.execute("""
            SELECT 
                parameter_name,
                display_name,
                parameter_type,
                default_value,
                description,
                is_user_configurable
            FROM global_parameters
            ORDER BY parameter_name
        """)
        all_global_params = [dict(row) for row in cursor.fetchall()]
        
        # Filter to only parameters referenced in prompt
        global_params = [
            p for p in all_global_params 
            if p['parameter_name'] in referenced_params
        ]
        
        # Get prompt-specific parameters (only those referenced in prompt)
        cursor.execute("""
            SELECT 
                pp.parameter_name,
                pp.display_name,
                pp.parameter_type,
                pp.default_value,
                pp.description,
                pp.is_required
            FROM prompt_parameters pp
            JOIN prompts p ON pp.prompt_id = p.id
            WHERE p.name = ?
            ORDER BY pp.parameter_name
        """, (prompt_name,))
        all_prompt_params = [dict(row) for row in cursor.fetchall()]
        
        # Filter to only parameters referenced in prompt
        prompt_params = [
            p for p in all_prompt_params 
            if p['parameter_name'] in referenced_params
        ]
        
        # Find undefined parameters (referenced but not in database)
        defined_params = set(p['parameter_name'] for p in global_params + prompt_params)
        undefined_params = referenced_params - defined_params
        
        # Create entries for undefined parameters
        undefined_param_list = [
            {
                "parameter_name": param,
                "display_name": param,
                "parameter_type": "undefined",
                "default_value": None,
                "description": "⚠️ Referenced in prompt but not defined in database",
                "is_user_configurable": False,
                "is_undefined": True
            }
            for param in sorted(undefined_params)
        ]
        
        # Fetch existing parameter overrides for this user/prompt (prompt-specific only)
        cursor.execute("""
            SELECT id FROM prompts WHERE name = ?
        """, (prompt_name,))
        prompt_row = cursor.fetchone()
        prompt_id = prompt_row[0] if prompt_row else None
        
        if prompt_id:
            cursor.execute("""
                SELECT 
                    gpo.parameter_name,
                    gpo.override_value,
                    CASE WHEN gpo.user_uuid IS NOT NULL THEN 'user' ELSE 'profile' END as override_scope
                FROM global_parameter_overrides gpo
                WHERE gpo.prompt_id = ?
                AND (gpo.user_uuid = ? OR gpo.profile_id IN (
                    SELECT profile_id FROM profile_prompt_assignments WHERE user_uuid = ?
                ))
                AND gpo.is_active = 1
                ORDER BY CASE WHEN gpo.user_uuid IS NOT NULL THEN 1 ELSE 2 END
            """, (prompt_id, user_uuid, user_uuid))
        else:
            cursor.execute("SELECT NULL WHERE 1=0")  # Empty result
        
        overrides = {row['parameter_name']: {
            'override_value': row['override_value'],
            'override_scope': row['override_scope']
        } for row in cursor.fetchall()}
        
        # Merge override info into parameters
        for param in global_params:
            param_name = param['parameter_name']
            if param_name in overrides:
                param['override_value'] = overrides[param_name]['override_value']
                param['override_scope'] = overrides[param_name]['override_scope']
                param['has_override'] = True
            else:
                param['override_value'] = None
                param['has_override'] = False
        
        # Also merge overrides into prompt parameters
        for param in prompt_params:
            param_name = param['parameter_name']
            if param_name in overrides:
                param['override_value'] = overrides[param_name]['override_value']
                param['override_scope'] = overrides[param_name]['override_scope']
                param['has_override'] = True
            else:
                param['override_value'] = None
                param['has_override'] = False
        
        conn.close()
        
        return jsonify({
            "success": True,
            "prompt_name": prompt_name,
            "global_parameters": global_params,
            "prompt_parameters": prompt_params,
            "undefined_parameters": undefined_param_list,
            "total_parameters": len(global_params) + len(prompt_params),
            "total_undefined": len(undefined_param_list),
            "total_referenced": len(referenced_params)
        })
        
    except Exception as e:
        app_logger.error(f"Error getting parameters for '{prompt_name}': {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to get parameters: {str(e)}"
        }), 500


@system_prompts_bp.route('/<prompt_name>/parameters/<parameter_name>', methods=['PUT'])
@require_auth
@require_prompt_engineer_or_enterprise
async def save_parameter_override(current_user, prompt_name, parameter_name):
    """
    Save a parameter override for the current user/profile.
    Phase 4: Parameter override
    """
    try:
        loader = get_prompt_loader()
        user_uuid = current_user.id
        
        # Verify prompt exists
        metadata = loader.get_prompt_metadata(prompt_name)
        if not metadata:
            return jsonify({
                "success": False,
                "message": f"Prompt '{prompt_name}' not found"
            }), 404
        
        # Get request data
        data = await request.get_json()
        override_value = data.get('override_value')
        
        if override_value is None:
            return jsonify({
                "success": False,
                "message": "override_value is required"
            }), 400
        
        import sqlite3
        conn = sqlite3.connect(loader.db_path)
        cursor = conn.cursor()
        
        # Get prompt_id for this prompt first
        cursor.execute("SELECT id FROM prompts WHERE name = ?", (prompt_name,))
        prompt_row = cursor.fetchone()
        if not prompt_row:
            conn.close()
            return jsonify({
                "success": False,
                "message": f"Prompt '{prompt_name}' not found in database"
            }), 404
        
        prompt_id = prompt_row[0]
        
        # Check if parameter exists (either global or prompt-local)
        cursor.execute("""
            SELECT parameter_name FROM global_parameters 
            WHERE parameter_name = ?
        """, (parameter_name,))
        is_global = cursor.fetchone() is not None
        
        if not is_global:
            # Check if it's a prompt-local parameter
            cursor.execute("""
                SELECT parameter_name FROM prompt_parameters 
                WHERE parameter_name = ? AND prompt_id = ?
            """, (parameter_name, prompt_id))
            is_prompt_local = cursor.fetchone() is not None
            
            if not is_prompt_local:
                conn.close()
                return jsonify({
                    "success": False,
                    "message": f"Parameter '{parameter_name}' not found for prompt '{prompt_name}'"
                }), 404
        
        # Determine scope (Enterprise = user, PE = profile)
        license_info = loader._license_info
        tier = license_info.get('tier', 'Standard')
        
        if tier == 'Enterprise':
            # User-level, prompt-specific override
            cursor.execute("""
                INSERT OR REPLACE INTO global_parameter_overrides 
                (parameter_name, prompt_id, user_uuid, override_value, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (parameter_name, prompt_id, user_uuid, override_value))
        else:
            # Profile-level, prompt-specific override (Prompt Engineer)
            # Get user's profile
            cursor.execute("""
                SELECT profile_id FROM profile_prompt_assignments 
                WHERE user_uuid = ? LIMIT 1
            """, (user_uuid,))
            profile_row = cursor.fetchone()
            
            if not profile_row:
                conn.close()
                return jsonify({
                    "success": False,
                    "message": "No profile assigned to user"
                }), 400
            
            profile_id = profile_row[0]
            cursor.execute("""
                INSERT OR REPLACE INTO global_parameter_overrides 
                (parameter_name, prompt_id, profile_id, override_value, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (parameter_name, prompt_id, profile_id, override_value))
        
        conn.commit()
        conn.close()
        
        # Clear cache
        loader._parameter_cache.clear()
        
        return jsonify({
            "success": True,
            "message": f"Parameter override saved for '{parameter_name}'",
            "override_value": override_value,
            "scope": 'user' if tier == 'Enterprise' else 'profile'
        })
        
    except Exception as e:
        app_logger.error(f"Error saving parameter override: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"Failed to save override: {str(e)}"
        }), 500


@system_prompts_bp.route('/<prompt_name>/parameters/<parameter_name>', methods=['DELETE'])
@require_auth
@require_prompt_engineer_or_enterprise
async def delete_parameter_override(current_user, prompt_name, parameter_name):
    """
    Delete a parameter override.
    Phase 4: Parameter override
    """
    try:
        loader = get_prompt_loader()
        user_uuid = current_user.id
        
        import sqlite3
        conn = sqlite3.connect(loader.db_path)
        cursor = conn.cursor()
        
        # Get prompt_id
        cursor.execute("SELECT id FROM prompts WHERE name = ?", (prompt_name,))
        prompt_row = cursor.fetchone()
        if not prompt_row:
            conn.close()
            return jsonify({
                "success": False,
                "message": f"Prompt '{prompt_name}' not found"
            }), 404
        
        prompt_id = prompt_row[0]
        
        # Delete user or profile override for this specific prompt
        cursor.execute("""
            DELETE FROM global_parameter_overrides
            WHERE parameter_name = ? 
            AND prompt_id = ?
            AND (user_uuid = ? OR profile_id IN (
                SELECT profile_id FROM profile_prompt_assignments WHERE user_uuid = ?
            ))
        """, (parameter_name, prompt_id, user_uuid, user_uuid))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        # Clear cache
        loader._parameter_cache.clear()
        
        return jsonify({
            "success": True,
            "message": f"Parameter override deleted for '{parameter_name}'",
            "deleted": deleted_count > 0
        })
        
    except Exception as e:
        app_logger.error(f"Error deleting parameter override: {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to delete override: {str(e)}"
        }), 500


@system_prompts_bp.route('/<prompt_name>/versions', methods=['GET'])
@require_auth
async def get_prompt_versions(current_user, prompt_name):
    """
    Get version history for a prompt.
    Phase 4: Version history viewer
    """
    try:
        loader = get_prompt_loader()
        
        # Verify prompt exists
        metadata = loader.get_prompt_metadata(prompt_name)
        if not metadata:
            return jsonify({
                "success": False,
                "message": f"Prompt '{prompt_name}' not found"
            }), 404
        
        import sqlite3
        conn = sqlite3.connect(loader.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check which version is currently pinned as active (if any)
        user_uuid = current_user.id
        license_info = APP_STATE.get('license_info') or {}
        license_tier = license_info.get('tier', 'Standard')
        active_version_id = None
        
        if license_tier == 'Enterprise':
            cursor.execute("""
                SELECT active_version_id FROM prompt_overrides po
                JOIN prompts p ON po.prompt_id = p.id
                WHERE p.name = ? AND po.user_uuid = ? AND po.is_active = 1
            """, (prompt_name, user_uuid))
            row = cursor.fetchone()
            if row:
                active_version_id = row['active_version_id']
        else:
            cursor.execute("""
                SELECT active_version_id FROM prompt_overrides po
                JOIN prompts p ON po.prompt_id = p.id
                WHERE p.name = ? AND po.profile_id IS NULL AND po.is_active = 1
            """, (prompt_name,))
            row = cursor.fetchone()
            if row:
                active_version_id = row['active_version_id']
        
        # Get version history (don't include content in list - too large)
        cursor.execute("""
            SELECT 
                pv.id,
                pv.version,
                pv.change_reason,
                pv.changed_by,
                pv.created_at,
                LENGTH(pv.content) as content_length,
                COALESCE(u.username, pv.changed_by) as author_display
            FROM prompt_versions pv
            JOIN prompts p ON pv.prompt_id = p.id
            LEFT JOIN users u ON pv.changed_by = u.id
            WHERE p.name = ?
            ORDER BY pv.version DESC
        """, (prompt_name,))
        
        rows = cursor.fetchall()
        versions = []
        
        # If no version is pinned (active_version_id is None), the latest version is active
        latest_version_id = rows[0]['id'] if rows else None
        
        for row in rows:
            version_dict = dict(row)
            # Mark which version is active (pinned, or latest if unpinned)
            if active_version_id is None:
                # No version pinned - latest is active
                version_dict['is_active'] = (row['id'] == latest_version_id)
            else:
                # Version pinned - only that version is active
                version_dict['is_active'] = (active_version_id == row['id'])
            versions.append(version_dict)
        
        conn.close()
        
        return jsonify({
            "success": True,
            "prompt_name": prompt_name,
            "versions": versions,
            "total_versions": len(versions),
            "current_version": metadata.get('version'),
            "active_version_id": active_version_id
        })
        
    except Exception as e:
        app_logger.error(f"Error getting versions for '{prompt_name}': {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to get version history: {str(e)}"
        }), 500


@system_prompts_bp.route('/<prompt_name>/versions/<int:version_number>', methods=['GET'])
@require_auth
async def get_specific_version(current_user, prompt_name, version_number):
    """
    Get a specific version of a prompt with decrypted content.
    Phase 4: Version viewer
    """
    try:
        loader = get_prompt_loader()
        
        # Verify prompt exists
        metadata = loader.get_prompt_metadata(prompt_name)
        if not metadata:
            return jsonify({
                "success": False,
                "message": f"Prompt '{prompt_name}' not found"
            }), 404
        
        import sqlite3
        conn = sqlite3.connect(loader.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get specific version from prompt_versions (including v1)
        cursor.execute("""
            SELECT 
                pv.id,
                pv.version,
                pv.content,
                pv.change_reason,
                pv.changed_by,
                pv.created_at
            FROM prompt_versions pv
            JOIN prompts p ON pv.prompt_id = p.id
            WHERE p.name = ? AND pv.version = ?
        """, (prompt_name, version_number))
        
        version_row = cursor.fetchone()
        conn.close()
        
        if not version_row:
            return jsonify({
                "success": False,
                "message": f"Version {version_number} not found for prompt '{prompt_name}'"
            }), 404
        
        # Decrypt the content (handle plain text from initial migration)
        from trusted_data_agent.agent.prompt_encryption import decrypt_prompt
        try:
            # Use silent_fail=True to suppress ERROR logs for Version 1 plain text
            decrypted_content = decrypt_prompt(version_row['content'], loader._decryption_key, silent_fail=True)
        except Exception as e:
            # Version might be plain text (initial migration data)
            app_logger.info(f"Version {version_number} of {prompt_name} is plain text (migration data)")
            decrypted_content = version_row['content']
        
        return jsonify({
            "success": True,
            "prompt_name": prompt_name,
            "version": version_row['version'],
            "content": decrypted_content,
            "change_reason": version_row['change_reason'],
            "changed_by": version_row['changed_by'],
            "created_at": version_row['created_at']
        })
        
    except Exception as e:
        app_logger.error(f"Error getting version {version_number} for '{prompt_name}': {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to get version: {str(e)}"
        }), 500


@system_prompts_bp.route('/<prompt_name>/versions/<int:version_number>/activate', methods=['POST'])
@require_auth
@require_prompt_engineer_or_enterprise
async def activate_version(current_user, prompt_name, version_number):
    """
    Activate a specific version (pin it as the active version).
    This sets active_version_id to point to the selected version without creating a new version.
    Phase 4: Version activation
    """
    try:
        loader = get_prompt_loader()
        
        # Verify prompt exists
        metadata = loader.get_prompt_metadata(prompt_name)
        if not metadata:
            return jsonify({
                "success": False,
                "message": f"Prompt '{prompt_name}' not found"
            }), 404
        
        import sqlite3
        conn = sqlite3.connect(loader.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            # Verify the version exists and get its ID
            cursor.execute("""
                SELECT pv.id
                FROM prompt_versions pv
                JOIN prompts p ON pv.prompt_id = p.id
                WHERE p.name = ? AND pv.version = ?
            """, (prompt_name, version_number))
            
            version_row = cursor.fetchone()
            
            if not version_row:
                conn.close()
                return jsonify({
                    "success": False,
                    "message": f"Version {version_number} not found for prompt '{prompt_name}'"
                }), 404
            
            version_id = version_row['id']
            
            # Determine scope
            license_info = APP_STATE.get('license_info') or {}
            license_tier = license_info.get('tier', 'Standard')
            user_uuid = current_user.id
            prompt_id = metadata['id']
            
            if license_tier == 'Enterprise':
                # Update user-level override (or create if doesn't exist)
                cursor.execute("""
                    SELECT id FROM prompt_overrides 
                    WHERE prompt_id = ? AND user_uuid = ? AND is_active = 1
                """, (prompt_id, user_uuid))
                
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing override to pin this version
                    cursor.execute("""
                        UPDATE prompt_overrides 
                        SET active_version_id = ?
                        WHERE id = ?
                    """, (version_id, existing['id']))
                else:
                    # Create new override with just the version pin (no content copy)
                    # We set content to empty and rely on active_version_id
                    cursor.execute("""
                        INSERT INTO prompt_overrides (prompt_id, user_uuid, content, active_version_id, created_by)
                        VALUES (?, ?, '', ?, ?)
                    """, (prompt_id, user_uuid, version_id, user_uuid))
                
                scope = 'user'
            else:
                # Prompt Engineer: Update profile-level override
                cursor.execute("""
                    SELECT id FROM prompt_overrides 
                    WHERE prompt_id = ? AND profile_id IS NULL AND is_active = 1
                """, (prompt_id,))
                
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing override to pin this version
                    cursor.execute("""
                        UPDATE prompt_overrides 
                        SET active_version_id = ?
                        WHERE id = ?
                    """, (version_id, existing['id']))
                else:
                    # Create new override with just the version pin
                    cursor.execute("""
                        INSERT INTO prompt_overrides (prompt_id, profile_id, content, active_version_id, created_by)
                        VALUES (?, NULL, '', ?, ?)
                    """, (prompt_id, version_id, user_uuid))
                
                scope = 'profile'
            
            conn.commit()
            
            # Clear cache
            keys_to_delete = [key for key in loader._prompt_cache.keys() if key.startswith(f"{prompt_name}:")]
            for key in keys_to_delete:
                del loader._prompt_cache[key]
            
            app_logger.info(f"Activated version {version_number} (ID: {version_id}) of {prompt_name} for user {current_user.username} ({scope}-level)")
            
            conn.close()
            
            return jsonify({
                "success": True,
                "message": f"Version {version_number} is now active (no new version created)",
                "prompt_name": prompt_name,
                "version": version_number,
                "scope": scope
            })
            
        except Exception as e:
            if conn:
                conn.rollback()
                conn.close()
            raise
        
    except Exception as e:
        app_logger.error(f"Error activating version {version_number} for '{prompt_name}': {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to activate version: {str(e)}"
        }), 500


@system_prompts_bp.route('/<prompt_name>/diff', methods=['GET'])
@require_auth
async def get_prompt_diff(current_user, prompt_name):
    """
    Compare base prompt with current override.
    Phase 4: Diff viewer
    """
    try:
        loader = get_prompt_loader()
        user_uuid = current_user.id
        
        # Verify prompt exists
        metadata = loader.get_prompt_metadata(prompt_name)
        if not metadata:
            return jsonify({
                "success": False,
                "message": f"Prompt '{prompt_name}' not found"
            }), 404
        
        # Get base content (decrypted) using prompt loader
        base_content = loader.get_prompt(prompt_name, user_uuid=None, profile_id=None, parameters={})
        
        # Get override content if exists
        import sqlite3
        conn = sqlite3.connect(loader.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check for user-level override first
        cursor.execute("""
            SELECT po.content, 'user' as override_scope
            FROM prompt_overrides po
            JOIN prompts p ON po.prompt_id = p.id
            WHERE p.name = ? AND po.user_uuid = ? AND po.is_active = 1
        """, (prompt_name, user_uuid))
        
        override_row = cursor.fetchone()
        
        # If no user override, check for profile override
        if not override_row:
            cursor.execute("""
                SELECT po.content, 'profile' as override_scope
                FROM prompt_overrides po
                JOIN prompts p ON po.prompt_id = p.id
                WHERE p.name = ? AND po.profile_id IS NULL AND po.is_active = 1
            """, (prompt_name,))
            override_row = cursor.fetchone()
        
        conn.close()
        
        # Decrypt override if exists
        override_content = None
        override_scope = None
        if override_row:
            from trusted_data_agent.agent.prompt_encryption import decrypt_prompt
            try:
                override_content = decrypt_prompt(override_row['content'], loader._decryption_key)
                override_scope = override_row['override_scope']
            except Exception as e:
                app_logger.error(f"Failed to decrypt override for {prompt_name}: {e}")
        
        return jsonify({
            "success": True,
            "prompt_name": prompt_name,
            "base_content": base_content,
            "override_content": override_content,
            "override_scope": override_scope,
            "has_override": override_content is not None,
            "base_length": len(base_content) if base_content else 0,
            "override_length": len(override_content) if override_content else 0
        })
        
    except Exception as e:
        app_logger.error(f"Error getting diff for '{prompt_name}': {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to get diff: {str(e)}"
        }), 500


@system_prompts_bp.route('/profiles', methods=['GET'])
@require_auth
async def list_profiles(current_user):
    """
    List available profiles for the current user.
    Phase 4: Profile selector
    """
    try:
        # For now, return profiles from tda_config.json
        # In future, this could come from database
        from trusted_data_agent.config_manager import ConfigManager
        
        config_mgr = ConfigManager()
        profiles = config_mgr.get_all_profiles()
        
        # Format for API response
        profile_list = []
        for profile_id, profile_data in profiles.items():
            profile_list.append({
                "id": profile_id,
                "name": profile_data.get("name", profile_id),
                "description": profile_data.get("description", ""),
                "is_default": profile_data.get("is_default", False)
            })
        
        return jsonify({
            "success": True,
            "profiles": profile_list,
            "total_count": len(profile_list)
        })
        
    except Exception as e:
        app_logger.error(f"Error listing profiles: {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to list profiles: {str(e)}"
        }), 500


# ===== Phase 4: Enhanced Admin UI Endpoints =====

@system_prompts_bp.route('/<prompt_name>/duplicate', methods=['POST'])
@require_auth
@require_prompt_engineer_or_enterprise
async def duplicate_prompt(current_user, prompt_name):
    """
    Duplicate an existing prompt with a new name.
    
    Request body:
    {
        "new_name": "MY_NEW_PROMPT",
        "new_display_name": "My New Prompt",
        "copy_parameters": true
    }
    """
    try:
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root
        
        data = await request.get_json()
        new_name = data.get('new_name')
        new_display_name = data.get('new_display_name')
        copy_parameters = data.get('copy_parameters', True)
        
        if not new_name:
            return jsonify({"success": False, "message": "new_name is required"}), 400
        
        if not new_display_name:
            new_display_name = new_name.replace('_', ' ').title()
        
        db_path = get_project_root() / 'tda_auth.db'
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get source prompt
        cursor.execute("SELECT * FROM prompts WHERE name = ?", (prompt_name,))
        source_prompt = cursor.fetchone()
        
        if not source_prompt:
            conn.close()
            return jsonify({"success": False, "message": f"Prompt '{prompt_name}' not found"}), 404
        
        # Check if new name already exists
        cursor.execute("SELECT id FROM prompts WHERE name = ?", (new_name,))
        if cursor.fetchone():
            conn.close()
            return jsonify({"success": False, "message": f"Prompt '{new_name}' already exists"}), 400
        
        # Create duplicate
        cursor.execute("""
            INSERT INTO prompts (name, display_name, content, description, class_id, role, provider, version, is_active, created_at, updated_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
        """, (
            new_name,
            new_display_name,
            source_prompt['content'],
            f"Duplicated from {prompt_name}",
            source_prompt['class_id'],
            source_prompt['role'],
            source_prompt['provider'],
            current_user.username
        ))
        
        new_prompt_id = cursor.lastrowid
        
        # Copy parameters if requested
        if copy_parameters:
            cursor.execute("""
                INSERT INTO prompt_parameters (prompt_id, parameter_name, display_name, parameter_type, parameter_scope, is_required, default_value, description)
                SELECT ?, parameter_name, display_name, parameter_type, parameter_scope, is_required, default_value, description
                FROM prompt_parameters
                WHERE prompt_id = ?
            """, (new_prompt_id, source_prompt['id']))
        
        # Create initial version entry
        cursor.execute("""
            INSERT INTO prompt_versions (prompt_id, version, content, changed_by, change_reason, created_at)
            VALUES (?, 1, ?, ?, 'Initial version (duplicated from ' || ? || ')', CURRENT_TIMESTAMP)
        """, (new_prompt_id, source_prompt['content'], current_user.username, prompt_name))
        
        conn.commit()
        conn.close()
        
        app_logger.info(f"User {current_user.username} duplicated prompt {prompt_name} to {new_name}")
        
        return jsonify({
            "success": True,
            "message": f"Prompt duplicated successfully",
            "new_prompt_id": new_prompt_id,
            "new_prompt_name": new_name
        })
        
    except Exception as e:
        app_logger.error(f"Error duplicating prompt {prompt_name}: {e}")
        return jsonify({"success": False, "message": f"Failed to duplicate prompt: {str(e)}"}), 500


@system_prompts_bp.route('/<prompt_name>/delete', methods=['DELETE'])
@require_auth
@require_prompt_engineer_or_enterprise
async def delete_prompt(current_user, prompt_name):
    """
    Delete a custom prompt.
    
    Safety checks:
    - Cannot delete default prompts (those in migration_data.sql)
    - Cannot delete prompts assigned to active profiles
    - Cannot delete prompts with active overrides
    """
    try:
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root
        
        db_path = get_project_root() / 'tda_auth.db'
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get prompt details
        cursor.execute("SELECT id, created_by FROM prompts WHERE name = ?", (prompt_name,))
        prompt_row = cursor.fetchone()
        
        if not prompt_row:
            conn.close()
            return jsonify({"success": False, "message": f"Prompt '{prompt_name}' not found"}), 404
        
        prompt_id, created_by = prompt_row
        
        # Check if this is a system default prompt (created_by is NULL or 'SYSTEM')
        # These are the prompts from the initial encryption/migration
        if created_by is None or created_by in ['SYSTEM', 'system', '']:
            conn.close()
            return jsonify({
                "success": False,
                "message": f"Cannot delete system default prompt '{prompt_name}'. Only user-created prompts can be deleted."
            }), 403
        
        # Check for active profile assignments
        cursor.execute("""
            SELECT COUNT(*) FROM profile_prompt_assignments 
            WHERE prompt_id = ? AND is_active = 1
        """, (prompt_id,))
        
        assignment_count = cursor.fetchone()[0]
        if assignment_count > 0:
            conn.close()
            return jsonify({
                "success": False,
                "message": f"Cannot delete prompt '{prompt_name}'. It is assigned to {assignment_count} active profile(s). Remove the assignments first."
            }), 403
        
        # Check for active overrides
        cursor.execute("""
            SELECT COUNT(*) FROM prompt_overrides 
            WHERE prompt_id = ? AND is_active = 1
        """, (prompt_id,))
        
        override_count = cursor.fetchone()[0]
        if override_count > 0:
            conn.close()
            return jsonify({
                "success": False,
                "message": f"Cannot delete prompt '{prompt_name}'. It has {override_count} active override(s). Delete the overrides first."
            }), 403
        
        # Delete related records (cascade)
        cursor.execute("DELETE FROM prompt_parameters WHERE prompt_id = ?", (prompt_id,))
        cursor.execute("DELETE FROM prompt_versions WHERE prompt_id = ?", (prompt_id,))
        cursor.execute("DELETE FROM profile_prompt_parameter_values WHERE prompt_id = ?", (prompt_id,))
        cursor.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        
        conn.commit()
        conn.close()
        
        app_logger.info(f"User {current_user.username} deleted prompt {prompt_name}")
        
        return jsonify({
            "success": True,
            "message": f"Prompt '{prompt_name}' deleted successfully"
        })
        
    except Exception as e:
        app_logger.error(f"Error deleting prompt {prompt_name}: {e}")
        return jsonify({"success": False, "message": f"Failed to delete prompt: {str(e)}"}), 500


@system_prompts_bp.route('/bulk/update', methods=['POST'])
@require_auth
@require_prompt_engineer_or_enterprise
async def bulk_update_prompts(current_user):
    """
    Bulk update multiple prompts.
    
    Request body:
    {
        "operations": [
            {"prompt_name": "PROMPT1", "action": "activate"},
            {"prompt_name": "PROMPT2", "action": "deactivate"},
            {"prompt_name": "PROMPT3", "action": "set_role", "role": "workflow"}
        ]
    }
    
    Supported actions:
    - activate: Set is_active = 1
    - deactivate: Set is_active = 0
    - set_role: Change role category
    - set_class: Change class_id
    """
    try:
        import sqlite3
        from trusted_data_agent.core.utils import get_project_root
        
        data = await request.get_json()
        operations = data.get('operations', [])
        
        if not operations:
            return jsonify({"success": False, "message": "No operations provided"}), 400
        
        db_path = get_project_root() / 'tda_auth.db'
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        results = []
        
        for op in operations:
            prompt_name = op.get('prompt_name')
            action = op.get('action')
            
            try:
                if action == 'activate':
                    cursor.execute("UPDATE prompts SET is_active = 1 WHERE name = ?", (prompt_name,))
                    results.append({"prompt": prompt_name, "status": "success", "action": action})
                    
                elif action == 'deactivate':
                    cursor.execute("UPDATE prompts SET is_active = 0 WHERE name = ?", (prompt_name,))
                    results.append({"prompt": prompt_name, "status": "success", "action": action})
                    
                elif action == 'set_role':
                    role = op.get('role')
                    cursor.execute("UPDATE prompts SET role = ? WHERE name = ?", (role, prompt_name))
                    results.append({"prompt": prompt_name, "status": "success", "action": action, "role": role})
                    
                elif action == 'set_class':
                    class_id = op.get('class_id')
                    cursor.execute("UPDATE prompts SET class_id = ? WHERE name = ?", (class_id, prompt_name))
                    results.append({"prompt": prompt_name, "status": "success", "action": action, "class_id": class_id})
                    
                else:
                    results.append({"prompt": prompt_name, "status": "error", "message": f"Unknown action: {action}"})
                    
            except Exception as e:
                results.append({"prompt": prompt_name, "status": "error", "message": str(e)})
        
        conn.commit()
        conn.close()
        
        success_count = sum(1 for r in results if r['status'] == 'success')
        
        app_logger.info(f"User {current_user.username} performed {success_count}/{len(operations)} bulk operations")
        
        return jsonify({
            "success": True,
            "message": f"Completed {success_count}/{len(operations)} operations",
            "results": results
        })
        
    except Exception as e:
        app_logger.error(f"Error in bulk update: {e}")
        return jsonify({"success": False, "message": f"Bulk update failed: {str(e)}"}), 500
