"""
Agent Pack REST API Endpoints

Provides pack-level orchestration endpoints. All actual CRUD is delegated to
AgentPackManager which calls existing internal APIs (ConfigManager,
CollectionDatabase, ChromaDB).

Endpoints:
- POST   /v1/agent-packs/import              Import an .agentpack file
- POST   /v1/agent-packs/export              Export a genie coordinator as .agentpack
- POST   /v1/agent-packs/create              Create .agentpack from selected profiles
- GET    /v1/agent-packs                     List installed packs
- GET    /v1/agent-packs/<installation_id>   Get pack details
- DELETE /v1/agent-packs/<installation_id>   Uninstall a pack
"""

import logging
import tempfile
from pathlib import Path

from quart import Blueprint, jsonify, request, send_file

from trusted_data_agent.auth.middleware import require_auth
from trusted_data_agent.core.agent_pack_manager import AgentPackManager

agent_pack_bp = Blueprint("agent_packs", __name__)
app_logger = logging.getLogger("quart.app")

DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"


def _manager() -> AgentPackManager:
    return AgentPackManager(db_path=str(DB_PATH))


# ── Import ────────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/agent-packs/import", methods=["POST"])
@require_auth
async def import_agent_pack(current_user):
    """Import an .agentpack file.

    Accepts either:
      - multipart/form-data  →  'file' field + optional 'mcp_server_id' field
      - application/json     →  {"import_path": "...", "mcp_server_id": "..."}
    """
    user_uuid = current_user.id
    tmp_path = None

    try:
        content_type = request.content_type or ""
        mcp_server_id = None
        llm_configuration_id = None
        conflict_strategy = None

        if "multipart/form-data" in content_type:
            files = await request.files
            if "file" not in files:
                return jsonify({"status": "error", "message": "No file provided"}), 400
            uploaded = files["file"]
            if not uploaded or not uploaded.filename:
                return jsonify({"status": "error", "message": "Invalid file"}), 400

            form = await request.form
            mcp_server_id = form.get("mcp_server_id") or None
            llm_configuration_id = form.get("llm_configuration_id") or None
            conflict_strategy = form.get("conflict_strategy") or None

            # Save to temp file
            tmp = tempfile.NamedTemporaryFile(suffix=".agentpack", delete=False)
            tmp_path = Path(tmp.name)
            await uploaded.save(str(tmp_path))
            zip_path = tmp_path

        elif "application/json" in content_type:
            data = await request.get_json()
            if not data or not data.get("import_path"):
                return jsonify({"status": "error", "message": "import_path is required"}), 400
            zip_path = Path(data["import_path"])
            if not zip_path.exists():
                return jsonify({"status": "error", "message": f"File not found: {zip_path}"}), 404
            mcp_server_id = data.get("mcp_server_id") or None
            llm_configuration_id = data.get("llm_configuration_id") or None
            conflict_strategy = data.get("conflict_strategy") or None

        else:
            return jsonify({
                "status": "error",
                "message": "Content-Type must be multipart/form-data or application/json",
            }), 400

        manager = _manager()
        result = await manager.import_pack(
            zip_path=zip_path,
            user_uuid=user_uuid,
            mcp_server_id=mcp_server_id,
            llm_configuration_id=llm_configuration_id,
            conflict_strategy=conflict_strategy,
        )
        return jsonify({"status": "success", **result}), 200

    except ValueError as e:
        app_logger.warning(f"Agent pack import validation error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
    except RuntimeError as e:
        app_logger.error(f"Agent pack import runtime error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        app_logger.error(f"Agent pack import failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Import failed: {e}"}), 500
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


# ── Export ────────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/agent-packs/export", methods=["POST"])
@require_auth
async def export_agent_pack(current_user):
    """Export a genie coordinator and its sub-profiles as an .agentpack file.

    Body (JSON): {"coordinator_profile_id": "profile-xxx"}
    Returns: .agentpack ZIP file download.
    """
    user_uuid = current_user.id

    try:
        data = await request.get_json()
        if not data or not data.get("coordinator_profile_id"):
            return jsonify({
                "status": "error",
                "message": "coordinator_profile_id is required",
            }), 400

        coordinator_profile_id = data["coordinator_profile_id"]
        manager = _manager()
        zip_path = await manager.export_pack(
            coordinator_profile_id=coordinator_profile_id,
            user_uuid=user_uuid,
        )

        return await send_file(
            str(zip_path),
            mimetype="application/zip",
            as_attachment=True,
            attachment_filename=zip_path.name,
        )

    except ValueError as e:
        app_logger.warning(f"Agent pack export validation error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
    except RuntimeError as e:
        app_logger.error(f"Agent pack export runtime error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        app_logger.error(f"Agent pack export failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Export failed: {e}"}), 500


# ── Create ───────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/agent-packs/create", methods=["POST"])
@require_auth
async def create_agent_pack(current_user):
    """Create an .agentpack file from selected profiles.

    Body (JSON): {"profile_ids": [...], "name": "...", "description": "..."}
    Returns: .agentpack ZIP file download.
    """
    user_uuid = current_user.id

    try:
        data = await request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Request body required"}), 400

        profile_ids = data.get("profile_ids", [])
        if not profile_ids:
            return jsonify({"status": "error", "message": "profile_ids is required"}), 400

        manager = _manager()
        zip_path = await manager.export_pack(
            profile_ids=profile_ids,
            user_uuid=user_uuid,
            pack_name=data.get("name", "Agent Pack"),
            pack_description=data.get("description", ""),
        )

        return await send_file(
            str(zip_path),
            mimetype="application/zip",
            as_attachment=True,
            attachment_filename=zip_path.name,
        )

    except ValueError as e:
        app_logger.warning(f"Agent pack create validation error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
    except RuntimeError as e:
        app_logger.error(f"Agent pack create runtime error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        app_logger.error(f"Agent pack create failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Create failed: {e}"}), 500


# ── List ──────────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/agent-packs", methods=["GET"])
@require_auth
async def list_agent_packs(current_user):
    """List installed agent packs for the current user."""
    user_uuid = current_user.id

    try:
        manager = _manager()
        packs = await manager.list_packs(user_uuid)
        return jsonify({"status": "success", "packs": packs}), 200

    except Exception as e:
        app_logger.error(f"Failed to list agent packs: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to list packs: {e}"}), 500


# ── Details ───────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/agent-packs/<int:installation_id>", methods=["GET"])
@require_auth
async def get_agent_pack_details(current_user, installation_id: int):
    """Get full details of an installed agent pack."""
    user_uuid = current_user.id

    try:
        manager = _manager()
        details = await manager.get_pack_details(installation_id, user_uuid)
        return jsonify({"status": "success", **details}), 200

    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception as e:
        app_logger.error(f"Failed to get agent pack details: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to get details: {e}"}), 500


# ── Uninstall ─────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/agent-packs/<int:installation_id>", methods=["DELETE"])
@require_auth
async def uninstall_agent_pack(current_user, installation_id: int):
    """Uninstall an agent pack — removes all profiles and collections it created."""
    user_uuid = current_user.id

    try:
        manager = _manager()
        result = await manager.uninstall_pack(installation_id, user_uuid)
        return jsonify({"status": "success", **result}), 200

    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except RuntimeError as e:
        app_logger.error(f"Agent pack uninstall error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        app_logger.error(f"Agent pack uninstall failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Uninstall failed: {e}"}), 500
