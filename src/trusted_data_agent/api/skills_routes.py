"""
REST API routes for skills management.

Skills are pre-processing prompt injections — reusable markdown knowledge/instruction
documents that get injected into the LLM's context when activated.

Endpoints:
- GET  /v1/skills                               — List available skills
- POST /v1/skills/reload                         — Hot-reload skills from disk
- GET  /v1/skills/activated                      — Get user's activated skills
- POST /v1/skills/<skill_id>/activate            — Activate a skill
- POST /v1/skills/activations/<name>/deactivate  — Deactivate a skill
- PUT  /v1/skills/activations/<name>/config      — Update default param
- PUT  /v1/skills/activations/<name>/rename      — Rename activation
- DELETE /v1/skills/activations/<name>           — Delete activation
- GET  /v1/skills/<skill_id>/content             — Get skill content (for editor)
- PUT  /v1/skills/<skill_id>                     — Update/create skill (save)
- DELETE /v1/skills/<skill_id>                   — Delete user-created skill
- POST /v1/skills/<skill_id>/export              — Export skill as .zip
- POST /v1/skills/import                         — Import skill from .zip
"""

import json
import logging
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from quart import Blueprint, jsonify, request, send_file

from trusted_data_agent.auth.admin import get_current_user_from_request

skills_api_bp = Blueprint("skills_api", __name__)
app_logger = logging.getLogger("quart.app")


def _get_user_uuid_from_request():
    """Extract user ID from request (from auth token or header)."""
    user = get_current_user_from_request()
    if user:
        return user.id
    return None


# ---------------------------------------------------------------------------
# List & Discovery
# ---------------------------------------------------------------------------

@skills_api_bp.route("/v1/skills", methods=["GET"])
async def list_skills():
    """
    List all available skills (built-in + user).

    Enforces admin governance: disabled skills are filtered out.
    If user skills are disabled, hides user-created skills.

    Returns:
        { "skills": [...], "_settings": { "user_skills_enabled": bool } }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.manager import get_skill_manager
        from trusted_data_agent.skills.settings import get_skill_settings, is_skill_available

        manager = get_skill_manager()
        skills = manager.list_skills()

        # Enforce admin governance
        skills = [s for s in skills if is_skill_available(s["skill_id"])]

        # If user skills disabled, hide user-created skills
        settings = get_skill_settings()
        if not settings.get("user_skills_enabled", True):
            skills = [s for s in skills if s.get("is_builtin")]

        return jsonify({
            "skills": skills,
            "_settings": {
                "user_skills_enabled": settings.get("user_skills_enabled", True),
            }
        }), 200

    except Exception as e:
        app_logger.error(f"Failed to list skills: {e}", exc_info=True)
        return jsonify({"error": "Failed to list skills."}), 500


@skills_api_bp.route("/v1/skills/reload", methods=["POST"])
async def reload_skills():
    """Hot-reload all skills from disk without restarting the application."""
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.manager import get_skill_manager

        manager = get_skill_manager()
        manager.reload()

        return jsonify({
            "status": "success",
            "loaded": len(manager.manifests),
            "skills": list(manager.manifests.keys())
        }), 200

    except Exception as e:
        app_logger.error(f"Failed to reload skills: {e}", exc_info=True)
        return jsonify({"error": "Failed to reload skills."}), 500


# ---------------------------------------------------------------------------
# User Activations
# ---------------------------------------------------------------------------

@skills_api_bp.route("/v1/skills/activated", methods=["GET"])
async def get_activated_skills():
    """
    Get the current user's activated skills, merged with manifest metadata.

    This is what the frontend uses for ! autocomplete.
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.db import get_user_activated_skills
        from trusted_data_agent.skills.manager import get_skill_manager
        from trusted_data_agent.skills.settings import is_skill_available

        activations = get_user_activated_skills(user_uuid)
        manager = get_skill_manager()

        # Merge activation data with manifest metadata
        result = []
        for activation in activations:
            skill_id = activation["skill_id"]
            if not is_skill_available(skill_id):
                continue
            skill_info = next(
                (s for s in manager.list_skills() if s["skill_id"] == skill_id),
                None,
            )
            if skill_info:
                merged = {**skill_info, **activation}
                result.append(merged)

        return jsonify({"skills": result}), 200

    except Exception as e:
        app_logger.error(f"Failed to get activated skills: {e}", exc_info=True)
        return jsonify({"error": "Failed to get activated skills."}), 500


@skills_api_bp.route("/v1/skills/<skill_id>/activate", methods=["POST"])
async def activate_skill_endpoint(skill_id: str):
    """
    Activate a skill for the current user.

    Request body (optional):
    {
        "default_param": "strict",
        "config": {"key": "value"},
        "activation_name": "myalias"  (optional — auto-generated if omitted)
    }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.db import activate_skill
        from trusted_data_agent.skills.manager import get_skill_manager
        from trusted_data_agent.skills.settings import is_skill_available

        # Enforce admin governance
        if not is_skill_available(skill_id):
            return jsonify({"error": f"Skill '{skill_id}' has been disabled by the administrator."}), 403

        # Validate skill exists
        manager = get_skill_manager()
        if skill_id not in manager.manifests:
            return jsonify({"error": f"Skill '{skill_id}' not found."}), 404

        data = await request.get_json() or {}
        default_param = data.get("default_param")
        config = data.get("config")
        activation_name = data.get("activation_name")

        success, generated_name = activate_skill(
            user_uuid, skill_id, default_param, config, activation_name
        )
        if success:
            return jsonify({
                "status": "activated",
                "skill_id": skill_id,
                "activation_name": generated_name,
            }), 200
        else:
            return jsonify({"error": "Failed to activate skill. Name may already be in use."}), 409

    except Exception as e:
        app_logger.error(f"Failed to activate skill '{skill_id}': {e}", exc_info=True)
        return jsonify({"error": "Failed to activate skill."}), 500


@skills_api_bp.route("/v1/skills/activations/<activation_name>/deactivate", methods=["POST"])
async def deactivate_skill_endpoint(activation_name: str):
    """Deactivate a skill activation by its activation_name."""
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.db import deactivate_skill

        success = deactivate_skill(user_uuid, activation_name)
        if success:
            return jsonify({"status": "deactivated", "activation_name": activation_name}), 200
        else:
            return jsonify({"error": f"Activation '{activation_name}' not found."}), 404

    except Exception as e:
        app_logger.error(f"Failed to deactivate skill '{activation_name}': {e}", exc_info=True)
        return jsonify({"error": "Failed to deactivate skill."}), 500


@skills_api_bp.route("/v1/skills/activations/<activation_name>/config", methods=["PUT"])
async def update_skill_config_endpoint(activation_name: str):
    """
    Update configuration for a skill activation.

    Request body:
    {
        "default_param": "lenient",
        "config": {"key": "value"}
    }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.db import update_skill_config

        data = await request.get_json() or {}
        default_param = data.get("default_param")
        config = data.get("config")

        success = update_skill_config(user_uuid, activation_name, default_param, config)
        if success:
            return jsonify({"status": "updated", "activation_name": activation_name}), 200
        else:
            return jsonify({"error": f"Activation '{activation_name}' is not active."}), 404

    except Exception as e:
        app_logger.error(f"Failed to update skill config: {e}", exc_info=True)
        return jsonify({"error": "Failed to update skill config."}), 500


@skills_api_bp.route("/v1/skills/activations/<activation_name>/rename", methods=["PUT"])
async def rename_skill_activation_endpoint(activation_name: str):
    """
    Rename a skill activation.

    Request body:
    { "new_name": "my_custom_name" }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.db import rename_skill_activation

        data = await request.get_json() or {}
        new_name = data.get("new_name")
        if not new_name:
            return jsonify({"error": "new_name is required."}), 400

        success = rename_skill_activation(user_uuid, activation_name, new_name)
        if success:
            return jsonify({
                "status": "renamed",
                "old_name": activation_name,
                "new_name": new_name,
            }), 200
        else:
            return jsonify({"error": f"Rename failed. Name '{new_name}' may already be in use."}), 409

    except Exception as e:
        app_logger.error(f"Failed to rename skill '{activation_name}': {e}", exc_info=True)
        return jsonify({"error": "Failed to rename skill."}), 500


@skills_api_bp.route("/v1/skills/activations/<activation_name>", methods=["DELETE"])
async def delete_skill_activation_endpoint(activation_name: str):
    """Hard-delete a skill activation (removes the row entirely)."""
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.db import delete_skill_activation

        success = delete_skill_activation(user_uuid, activation_name)
        if success:
            return jsonify({"status": "deleted", "activation_name": activation_name}), 200
        else:
            return jsonify({"error": f"Activation '{activation_name}' not found."}), 404

    except Exception as e:
        app_logger.error(f"Failed to delete skill '{activation_name}': {e}", exc_info=True)
        return jsonify({"error": "Failed to delete skill activation."}), 500


# ---------------------------------------------------------------------------
# Skill Content & CRUD
# ---------------------------------------------------------------------------

@skills_api_bp.route("/v1/skills/<skill_id>/content", methods=["GET"])
async def get_skill_content(skill_id: str):
    """
    Get the full content and manifest of a skill for the editor.

    Returns:
    {
        "skill_id": "sql-expert",
        "content": "# SQL Expert\n...",
        "manifest": { ... },
        "is_builtin": true,
        "file_path": "/path/to/skill.md"
    }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.manager import get_skill_manager

        manager = get_skill_manager()

        if skill_id not in manager.manifests:
            return jsonify({"error": f"Skill '{skill_id}' not found."}), 404

        content = manager.get_skill_full_content(skill_id)
        manifest = manager.get_skill_manifest(skill_id)

        # Determine file path and builtin status from raw manifest
        raw_manifest = manager.manifests[skill_id]
        file_path = str(raw_manifest.get("_dir", "")) if raw_manifest else ""
        is_builtin = not raw_manifest.get("_is_user", False) if raw_manifest else True

        return jsonify({
            "skill_id": skill_id,
            "content": content or "",
            "manifest": manifest or {},
            "is_builtin": is_builtin,
            "file_path": file_path,
        }), 200

    except Exception as e:
        app_logger.error(f"Failed to get skill content for '{skill_id}': {e}", exc_info=True)
        return jsonify({"error": "Failed to get skill content."}), 500


@skills_api_bp.route("/v1/skills/<skill_id>", methods=["PUT"])
async def save_skill_endpoint(skill_id: str):
    """
    Create or update a user skill.

    Saves to ~/.tda/skills/<skill_id>/ directory.
    Built-in skills cannot be overwritten directly — saving creates a user override.

    Request body:
    {
        "content": "# My Skill\n\nInstructions...",
        "manifest": {
            "name": "my-skill",
            "description": "...",
            "tags": ["tag1"],
            ...
        }
    }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.settings import are_user_skills_enabled
        if not are_user_skills_enabled():
            return jsonify({
                "error": "Custom skill creation has been disabled by the administrator."
            }), 403

        from trusted_data_agent.skills.manager import get_skill_manager

        data = await request.get_json()
        if not data:
            return jsonify({"error": "No data provided."}), 400

        content = data.get("content", "")
        manifest_data = data.get("manifest", {})

        if not content.strip():
            return jsonify({"error": "Skill content cannot be empty."}), 400

        manager = get_skill_manager()
        manager.save_skill(skill_id, content, manifest_data)

        return jsonify({
            "status": "saved",
            "skill_id": skill_id,
            "message": f"Skill '{skill_id}' saved successfully.",
        }), 200

    except Exception as e:
        app_logger.error(f"Failed to save skill '{skill_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save skill: {str(e)}"}), 500


@skills_api_bp.route("/v1/skills/<skill_id>", methods=["DELETE"])
async def delete_skill_endpoint(skill_id: str):
    """
    Delete a user-created skill from disk.

    Rejects if:
      - Skill is built-in (403)
      - Skill not found (404)
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.manager import get_skill_manager

        manager = get_skill_manager()

        if skill_id not in manager.manifests:
            return jsonify({"error": f"Skill '{skill_id}' not found."}), 404

        manager.delete_skill(skill_id)

        return jsonify({
            "status": "deleted",
            "skill_id": skill_id,
            "message": f"Skill '{skill_id}' deleted.",
        }), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        app_logger.error(f"Failed to delete skill '{skill_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to delete skill: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Import / Export
# ---------------------------------------------------------------------------

@skills_api_bp.route("/v1/skills/<skill_id>/export", methods=["POST"])
async def export_skill_endpoint(skill_id: str):
    """
    Export a skill as a downloadable .zip file.

    The archive contains:
        skill.json     — manifest metadata
        <name>.md      — markdown content

    Works for both built-in and user-created skills.
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.manager import get_skill_manager

        manager = get_skill_manager()

        if skill_id not in manager.manifests:
            return jsonify({"error": f"Skill '{skill_id}' not found."}), 404

        # Get content and manifest
        content = manager.get_skill_full_content(skill_id)
        manifest = dict(manager.get_skill_manifest(skill_id) or {})

        if not content:
            return jsonify({"error": f"Could not retrieve content for '{skill_id}'."}), 404

        # Clean internal metadata keys
        for internal_key in ("_is_user", "_source_path", "_dir", "_auto_generated"):
            manifest.pop(internal_key, None)

        manifest["export_format_version"] = "1.0"
        manifest["exported_at"] = datetime.now(timezone.utc).isoformat()

        # Ensure name is present
        if "name" not in manifest:
            manifest["name"] = skill_id

        # Determine the markdown filename
        main_file = manifest.get("main_file", f"{skill_id}.md")

        # Create ZIP in temp directory
        tmp_dir = tempfile.mkdtemp()
        zip_filename = f"{skill_id}.zip"
        zip_path = Path(tmp_dir) / zip_filename

        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("skill.json", json.dumps(manifest, indent=2))
            zf.writestr(main_file, content)

        return await send_file(
            str(zip_path),
            mimetype="application/zip",
            as_attachment=True,
            attachment_filename=zip_filename,
        )

    except Exception as e:
        app_logger.error(f"Failed to export skill '{skill_id}': {e}", exc_info=True)
        return jsonify({"error": f"Export failed: {str(e)}"}), 500


@skills_api_bp.route("/v1/skills/import", methods=["POST"])
async def import_skill_endpoint():
    """
    Import a skill from an uploaded .zip file.

    Accepts multipart/form-data with a 'file' field.
    Extracts skill.json + *.md to ~/.tda/skills/<skill_id>/
    and hot-reloads the skill manager.

    Compatible with Claude Code skills (skill.json + name.md).
    """
    tmp_path = None
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.settings import are_user_skills_enabled
        if not are_user_skills_enabled():
            return jsonify({
                "error": "Custom skill creation has been disabled by the administrator."
            }), 403

        # Get uploaded file
        files = await request.files
        if "file" not in files:
            return jsonify({"error": "No file uploaded. Use 'file' field."}), 400

        uploaded = files["file"]
        if not uploaded.filename:
            return jsonify({"error": "Empty filename."}), 400

        # Save to temp file
        tmp_dir = tempfile.mkdtemp()
        tmp_path = Path(tmp_dir) / uploaded.filename
        await uploaded.save(str(tmp_path))

        # Validate it's a valid zip
        if not zipfile.is_zipfile(str(tmp_path)):
            return jsonify({"error": "Uploaded file is not a valid ZIP archive."}), 400

        # Extract and validate contents
        manifest_data = None
        md_content = None
        md_filename = None

        with zipfile.ZipFile(str(tmp_path), "r") as zf:
            names = zf.namelist()

            # Find skill.json (may be at root or in a subdirectory)
            manifest_candidates = [n for n in names if n.endswith("skill.json")]
            if not manifest_candidates:
                return jsonify({"error": "No skill.json found in archive."}), 400

            manifest_path = manifest_candidates[0]
            manifest_data = json.loads(zf.read(manifest_path).decode("utf-8"))

            # Find .md file
            md_candidates = [n for n in names if n.endswith(".md")]
            if not md_candidates:
                return jsonify({"error": "No .md file found in archive."}), 400

            md_filename = md_candidates[0]
            md_content = zf.read(md_filename).decode("utf-8")

        # Determine skill ID from manifest
        skill_id = manifest_data.get("name")
        if not skill_id:
            # Fall back to filename without extension
            skill_id = Path(md_filename).stem

        # Clean export metadata
        manifest_data.pop("export_format_version", None)
        manifest_data.pop("exported_at", None)

        # Ensure main_file points to the correct filename
        actual_md_name = Path(md_filename).name
        manifest_data["main_file"] = actual_md_name

        # Save to user skills directory
        from trusted_data_agent.skills.manager import get_skill_manager

        manager = get_skill_manager()
        manager.save_skill(skill_id, md_content, manifest_data)

        return jsonify({
            "status": "imported",
            "skill_id": skill_id,
            "name": manifest_data.get("name", skill_id),
            "description": manifest_data.get("description", ""),
            "message": f"Skill '{skill_id}' imported successfully.",
        }), 201

    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON in skill.json manifest."}), 400
    except Exception as e:
        app_logger.error(f"Failed to import skill: {e}", exc_info=True)
        return jsonify({"error": f"Import failed: {str(e)}"}), 500
    finally:
        # Cleanup temp file
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
