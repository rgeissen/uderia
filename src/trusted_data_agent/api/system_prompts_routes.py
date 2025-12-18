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
        
        # Get content (with overrides if user has access)
        user_uuid = current_user.id
        content = loader.get_prompt(prompt_name, user_uuid=user_uuid)
        
        # Check if this user/profile has overrides
        has_override = False  # TODO: Query database for override existence
        
        return jsonify({
            "success": True,
            "prompt_name": prompt_name,
            "content": content,
            "is_override": has_override,
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
        
        conn = sqlite3.connect(loader.db_path)
        cursor = conn.cursor()
        
        # Get prompt_id
        cursor.execute("SELECT id FROM prompts WHERE name = ?", (prompt_name,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "message": "Prompt not found"}), 404
        
        prompt_id = row[0]
        
        if license_tier == 'Enterprise':
            # User-level override
            cursor.execute("""
                INSERT OR REPLACE INTO prompt_overrides 
                (prompt_id, user_id, override_content, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?)
            """, (prompt_id, user_uuid, content, user_uuid, user_uuid))
            scope = 'user'
        else:
            # Profile-level override (Prompt Engineer tier)
            # For now, we'll use a default profile or create a mechanism to select profile
            # This is a simplified implementation
            cursor.execute("""
                INSERT OR REPLACE INTO prompt_overrides 
                (prompt_id, profile_id, override_content, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?)
            """, (prompt_id, 'default', content, user_uuid, user_uuid))
            scope = 'profile'
        
        conn.commit()
        conn.close()
        
        # Clear cache
        if prompt_name in loader._prompt_cache:
            del loader._prompt_cache[prompt_name]
        
        app_logger.info(f"System prompt override saved: {prompt_name} ({scope}-level)")
        
        return jsonify({
            "success": True,
            "message": f"System prompt '{prompt_name}' saved successfully ({scope}-level override)",
            "prompt_name": prompt_name,
            "override_scope": scope
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
            WHERE prompt_id = ? AND (user_id = ? OR profile_id IN (
                SELECT profile_id FROM profile_prompt_assignments WHERE user_id = ?
            ))
        """, (prompt_id, user_uuid, user_uuid))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        # Clear cache
        if prompt_name in loader._prompt_cache:
            del loader._prompt_cache[prompt_name]
        
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
