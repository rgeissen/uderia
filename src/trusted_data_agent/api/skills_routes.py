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
- POST /v1/skills/<skill_id>/export              — Export skill as .skill (Claude Code compatible)
- POST /v1/skills/import                         — Import skill from .skill/.zip

Marketplace:
- POST /v1/skills/<skill_id>/publish             — Publish skill to marketplace
- GET  /v1/marketplace/skills                     — Browse marketplace
- GET  /v1/marketplace/skills/<id>                — Skill detail + ratings
- POST /v1/marketplace/skills/<id>/install        — Install from marketplace
- POST /v1/marketplace/skills/<id>/rate           — Rate/review
- DELETE /v1/marketplace/skills/<id>              — Unpublish
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
                "user_skills_marketplace_enabled": settings.get("user_skills_marketplace_enabled", True),
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
        zip_filename = f"{skill_id}.skill"
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


# ============================================================================
# SKILL MARKETPLACE ENDPOINTS
# ============================================================================

@skills_api_bp.route("/v1/skills/<skill_id>/publish", methods=["POST"])
async def publish_skill(skill_id: str):
    """
    Publish a user-created skill to the marketplace.

    Body (JSON, optional):
    {
        "visibility": "public" | "targeted",
        "user_ids": ["uuid1", "uuid2"]  (required if targeted)
    }
    """
    import hashlib
    import sqlite3
    import uuid as _uuid

    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.settings import is_skill_marketplace_enabled
        if not is_skill_marketplace_enabled():
            return jsonify({"error": "Skill marketplace has been disabled by the administrator."}), 403

        from trusted_data_agent.skills.manager import get_skill_manager
        manager = get_skill_manager()
        manifest = manager.get_skill_manifest(skill_id)
        if not manifest:
            return jsonify({"error": f"Skill '{skill_id}' not found."}), 404

        # Only user-created skills can be published
        if not manifest.get("_is_user"):
            return jsonify({"error": "Only user-created skills can be published."}), 400

        data = (await request.get_json()) or {}
        visibility = data.get("visibility", "public")
        user_ids = data.get("user_ids", [])

        if visibility not in ("public", "targeted"):
            return jsonify({"error": "Visibility must be 'public' or 'targeted'"}), 400
        if visibility == "targeted" and not user_ids:
            return jsonify({"error": "Targeted publish requires at least one user"}), 400

        # Get content for hashing
        content = manager.get_skill_full_content(skill_id) or ""
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        db_path = Path(__file__).resolve().parents[3] / "tda_auth.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check if already published by this user
        cursor.execute(
            "SELECT id FROM marketplace_skills WHERE skill_id = ? AND publisher_user_id = ?",
            (skill_id, user_uuid),
        )
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return jsonify({"error": "This skill is already published", "marketplace_id": existing["id"]}), 409

        marketplace_id = str(_uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Store manifest JSON for preview (strip internal keys)
        clean_manifest = {k: v for k, v in manifest.items() if not k.startswith("_")}

        # Extract skill-specific metadata
        uderia_section = manifest.get("uderia", {})
        injection_target = uderia_section.get("injection_target", "system_prompt")
        allowed_params = uderia_section.get("allowed_params", [])
        tags = manifest.get("tags", [])

        cursor.execute(
            """INSERT INTO marketplace_skills
               (id, skill_id, name, description, version, author,
                injection_target, has_params, tags_json,
                publisher_user_id, visibility, manifest_json, content_hash,
                download_count, install_count, published_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
            (
                marketplace_id, skill_id,
                manifest.get("name", skill_id),
                manifest.get("description", ""),
                manifest.get("version", "1.0.0"),
                manifest.get("author", "Unknown"),
                injection_target,
                1 if allowed_params else 0,
                json.dumps(tags),
                user_uuid, visibility,
                json.dumps(clean_manifest), content_hash,
                now, now,
            ),
        )

        # Store files in marketplace_data directory (Claude Code compatible format)
        marketplace_data = Path(__file__).resolve().parents[3] / "marketplace_data" / "skills" / marketplace_id
        marketplace_data.mkdir(parents=True, exist_ok=True)
        main_file = manifest.get("main_file", f"{skill_id}.md")
        (marketplace_data / "skill.json").write_text(json.dumps(clean_manifest, indent=2), encoding="utf-8")
        (marketplace_data / main_file).write_text(content, encoding="utf-8")

        # Targeted sharing grants
        if visibility == "targeted" and user_ids:
            for uid in user_ids:
                cursor.execute(
                    "INSERT OR IGNORE INTO marketplace_sharing_grants "
                    "(id, resource_type, resource_id, grantor_user_id, grantee_user_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(_uuid.uuid4()), "skill", marketplace_id, user_uuid, uid, now),
                )

        conn.commit()
        conn.close()

        app_logger.info(f"Skill '{skill_id}' published to marketplace (id={marketplace_id}, visibility={visibility})")
        return jsonify({
            "status": "success",
            "marketplace_id": marketplace_id,
            "message": "Skill published to marketplace",
        }), 200

    except Exception as e:
        app_logger.error(f"Skill publish failed: {e}", exc_info=True)
        return jsonify({"error": f"Publish failed: {e}"}), 500


@skills_api_bp.route("/v1/marketplace/skills", methods=["GET"])
async def browse_marketplace_skills():
    """
    Browse published skills with pagination, search, and sorting.

    Query params: page, per_page, search, sort_by, injection_target
    """
    import sqlite3

    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("per_page", 12)), 50)
        search = request.args.get("search", "").strip()
        sort_by = request.args.get("sort_by", "recent")
        injection_target = request.args.get("injection_target", "all")

        db_path = Path(__file__).resolve().parents[3] / "tda_auth.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Visibility filter: public + targeted for current user
        where_clauses = [
            "(s.visibility = 'public' OR (s.visibility = 'targeted' AND s.id IN "
            "(SELECT resource_id FROM marketplace_sharing_grants WHERE resource_type = 'skill' AND grantee_user_id = ?)))"
        ]
        params = [user_uuid]

        if injection_target != "all":
            where_clauses.append("s.injection_target = ?")
            params.append(injection_target)

        if search:
            where_clauses.append("(s.name LIKE ? OR s.description LIKE ? OR s.skill_id LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])

        where_sql = " AND ".join(where_clauses)

        sort_map = {
            "downloads": "s.download_count DESC",
            "installs": "s.install_count DESC",
            "rating": "avg_rating DESC",
            "recent": "s.published_at DESC",
            "name": "s.name ASC",
        }
        order_sql = sort_map.get(sort_by, "s.published_at DESC")

        cursor = conn.cursor()

        # Total count
        cursor.execute(f"SELECT COUNT(*) FROM marketplace_skills s WHERE {where_sql}", params)
        total = cursor.fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)

        # Fetch page with ratings JOIN
        offset = (page - 1) * per_page
        query = f"""
            SELECT s.*,
                   u.username AS publisher_username,
                   u.display_name AS publisher_display_name,
                   COALESCE(r.avg_rating, 0) AS avg_rating,
                   COALESCE(r.rating_count, 0) AS rating_count
            FROM marketplace_skills s
            LEFT JOIN users u ON s.publisher_user_id = u.id
            LEFT JOIN (
                SELECT skill_marketplace_id, AVG(rating) AS avg_rating, COUNT(*) AS rating_count
                FROM skill_ratings
                GROUP BY skill_marketplace_id
            ) r ON r.skill_marketplace_id = s.id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, params + [per_page, offset])
        rows = cursor.fetchall()

        skills = []
        for row in rows:
            skill = {
                "id": row["id"],
                "skill_id": row["skill_id"],
                "name": row["name"],
                "description": row["description"],
                "version": row["version"],
                "author": row["author"],
                "injection_target": row["injection_target"],
                "has_params": bool(row["has_params"]),
                "tags": json.loads(row["tags_json"]) if row["tags_json"] else [],
                "publisher_username": row["publisher_display_name"] or row["publisher_username"],
                "download_count": row["download_count"],
                "install_count": row["install_count"],
                "average_rating": round(row["avg_rating"], 1),
                "rating_count": row["rating_count"],
                "visibility": row["visibility"],
                "published_at": row["published_at"],
                "is_publisher": row["publisher_user_id"] == user_uuid,
            }
            skills.append(skill)

        conn.close()

        return jsonify({
            "status": "success",
            "skills": skills,
            "total": total,
            "total_pages": total_pages,
            "page": page,
            "per_page": per_page,
        }), 200

    except Exception as e:
        app_logger.error(f"Browse marketplace skills failed: {e}", exc_info=True)
        return jsonify({"error": f"Browse failed: {e}"}), 500


@skills_api_bp.route("/v1/marketplace/skills/<marketplace_id>", methods=["GET"])
async def get_marketplace_skill_detail(marketplace_id: str):
    """Get detail for a single marketplace skill."""
    import sqlite3

    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        db_path = Path(__file__).resolve().parents[3] / "tda_auth.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """SELECT s.*,
                      u.username AS publisher_username,
                      u.display_name AS publisher_display_name,
                      COALESCE(r.avg_rating, 0) AS avg_rating,
                      COALESCE(r.rating_count, 0) AS rating_count
               FROM marketplace_skills s
               LEFT JOIN users u ON s.publisher_user_id = u.id
               LEFT JOIN (
                   SELECT skill_marketplace_id, AVG(rating) AS avg_rating, COUNT(*) AS rating_count
                   FROM skill_ratings GROUP BY skill_marketplace_id
               ) r ON r.skill_marketplace_id = s.id
               WHERE s.id = ?""",
            (marketplace_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Skill not found"}), 404

        # Get user's own rating
        cursor.execute(
            "SELECT rating, comment FROM skill_ratings WHERE skill_marketplace_id = ? AND user_id = ?",
            (marketplace_id, user_uuid),
        )
        user_rating_row = cursor.fetchone()

        conn.close()

        skill = {
            "id": row["id"],
            "skill_id": row["skill_id"],
            "name": row["name"],
            "description": row["description"],
            "version": row["version"],
            "author": row["author"],
            "injection_target": row["injection_target"],
            "has_params": bool(row["has_params"]),
            "tags": json.loads(row["tags_json"]) if row["tags_json"] else [],
            "manifest_json": json.loads(row["manifest_json"]) if row["manifest_json"] else {},
            "publisher_username": row["publisher_display_name"] or row["publisher_username"],
            "download_count": row["download_count"],
            "install_count": row["install_count"],
            "average_rating": round(row["avg_rating"], 1),
            "rating_count": row["rating_count"],
            "visibility": row["visibility"],
            "published_at": row["published_at"],
            "is_publisher": row["publisher_user_id"] == user_uuid,
            "user_rating": dict(user_rating_row) if user_rating_row else None,
        }

        return jsonify({"status": "success", "skill": skill}), 200

    except Exception as e:
        app_logger.error(f"Get marketplace skill detail failed: {e}", exc_info=True)
        return jsonify({"error": f"Failed to get skill detail: {e}"}), 500


@skills_api_bp.route("/v1/marketplace/skills/<marketplace_id>/install", methods=["POST"])
async def install_marketplace_skill(marketplace_id: str):
    """
    Install a marketplace skill into the user's ~/.tda/skills/ directory.
    Copies skill.json + .md content, hot-reloads the skill manager, increments install_count.
    """
    import sqlite3

    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.skills.settings import is_skill_marketplace_enabled
        if not is_skill_marketplace_enabled():
            return jsonify({"error": "Skill marketplace has been disabled by the administrator."}), 403

        db_path = Path(__file__).resolve().parents[3] / "tda_auth.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM marketplace_skills WHERE id = ?", (marketplace_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Skill not found in marketplace"}), 404

        skill_id = row["skill_id"]

        # Read files from marketplace_data (Claude Code compatible format)
        marketplace_data = Path(__file__).resolve().parents[3] / "marketplace_data" / "skills" / marketplace_id
        manifest_path = marketplace_data / "skill.json"

        if not manifest_path.exists():
            conn.close()
            return jsonify({"error": "Skill manifest not found"}), 404

        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)

        # Find the .md content file
        main_file = manifest.get("main_file", f"{skill_id}.md")
        content_path = marketplace_data / main_file
        if not content_path.exists():
            # Try any .md file in the directory
            md_files = list(marketplace_data.glob("*.md"))
            if md_files:
                content_path = md_files[0]
                main_file = content_path.name
            else:
                conn.close()
                return jsonify({"error": "Skill content not found"}), 404

        content = content_path.read_text(encoding="utf-8")

        # Save to ~/.tda/skills/<skill_id>/ using the skill manager
        from trusted_data_agent.skills.manager import get_skill_manager
        manager = get_skill_manager()
        manager.save_skill(skill_id, content, manifest)

        # Hot-reload
        manager.reload()

        # Increment install_count
        cursor.execute(
            "UPDATE marketplace_skills SET install_count = install_count + 1 WHERE id = ?",
            (marketplace_id,),
        )
        conn.commit()
        conn.close()

        app_logger.info(f"User {user_uuid} installed marketplace skill '{skill_id}' (marketplace_id={marketplace_id})")
        return jsonify({
            "status": "success",
            "skill_id": skill_id,
            "message": f"Skill '{row['name']}' installed successfully",
        }), 200

    except Exception as e:
        app_logger.error(f"Install marketplace skill failed: {e}", exc_info=True)
        return jsonify({"error": f"Install failed: {e}"}), 500


@skills_api_bp.route("/v1/marketplace/skills/<marketplace_id>/rate", methods=["POST"])
async def rate_marketplace_skill(marketplace_id: str):
    """
    Rate a marketplace skill.

    Body (JSON): {"rating": 5, "comment": "Great skill!"}
    """
    import sqlite3
    import uuid as _uuid

    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        data = await request.get_json()
        if not data or "rating" not in data:
            return jsonify({"error": "rating is required"}), 400

        rating = int(data["rating"])
        if rating < 1 or rating > 5:
            return jsonify({"error": "rating must be between 1 and 5"}), 400

        comment = data.get("comment", "").strip() or None

        db_path = Path(__file__).resolve().parents[3] / "tda_auth.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Verify skill exists
        cursor.execute("SELECT id, publisher_user_id FROM marketplace_skills WHERE id = ?", (marketplace_id,))
        skill_row = cursor.fetchone()
        if not skill_row:
            conn.close()
            return jsonify({"error": "Skill not found"}), 404

        # Cannot rate own skill
        if skill_row["publisher_user_id"] == user_uuid:
            conn.close()
            return jsonify({"error": "Cannot rate your own skill"}), 400

        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "SELECT id FROM skill_ratings WHERE skill_marketplace_id = ? AND user_id = ?",
            (marketplace_id, user_uuid),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE skill_ratings SET rating = ?, comment = ?, updated_at = ? WHERE id = ?",
                (rating, comment, now, existing["id"]),
            )
            rating_id = existing["id"]
            message = "Rating updated successfully"
            status_code = 200
        else:
            rating_id = str(_uuid.uuid4())
            cursor.execute(
                "INSERT INTO skill_ratings (id, skill_marketplace_id, user_id, rating, comment, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rating_id, marketplace_id, user_uuid, rating, comment, now, now),
            )
            message = "Rating submitted successfully"
            status_code = 201

        conn.commit()
        conn.close()

        return jsonify({"status": "success", "rating_id": rating_id, "message": message}), status_code

    except Exception as e:
        app_logger.error(f"Skill rating failed: {e}", exc_info=True)
        return jsonify({"error": f"Rating failed: {e}"}), 500


@skills_api_bp.route("/v1/marketplace/skills/<marketplace_id>", methods=["DELETE"])
async def unpublish_skill(marketplace_id: str):
    """Unpublish a skill from the marketplace (publisher only)."""
    import sqlite3

    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        db_path = Path(__file__).resolve().parents[3] / "tda_auth.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, skill_id FROM marketplace_skills WHERE id = ? AND publisher_user_id = ?",
            (marketplace_id, user_uuid),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Skill not found or you are not the publisher"}), 404

        # Delete sharing grants
        cursor.execute(
            "DELETE FROM marketplace_sharing_grants WHERE resource_type = 'skill' AND resource_id = ?",
            (marketplace_id,),
        )
        # Delete ratings
        cursor.execute(
            "DELETE FROM skill_ratings WHERE skill_marketplace_id = ?",
            (marketplace_id,),
        )
        # Delete marketplace record
        cursor.execute("DELETE FROM marketplace_skills WHERE id = ?", (marketplace_id,))

        conn.commit()
        conn.close()

        # Clean up marketplace_data files
        marketplace_data = Path(__file__).resolve().parents[3] / "marketplace_data" / "skills" / marketplace_id
        if marketplace_data.exists():
            import shutil
            shutil.rmtree(marketplace_data, ignore_errors=True)

        app_logger.info(f"Skill '{row['skill_id']}' unpublished from marketplace (id={marketplace_id})")
        return jsonify({"status": "success", "message": "Skill unpublished"}), 200

    except Exception as e:
        app_logger.error(f"Unpublish skill failed: {e}", exc_info=True)
        return jsonify({"error": f"Unpublish failed: {e}"}), 500
