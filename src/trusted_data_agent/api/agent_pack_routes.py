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

Marketplace endpoints:
- POST   /v1/agent-packs/<installation_id>/publish    Publish to marketplace (metadata only)
- GET    /v1/marketplace/agent-packs                  Browse published packs
- GET    /v1/marketplace/agent-packs/<pack_id>        Pack details
- POST   /v1/marketplace/agent-packs/<pack_id>/install Subscribe (logical sharing grant)
- POST   /v1/marketplace/agent-packs/<pack_id>/rate   Rate a pack
- DELETE /v1/marketplace/agent-packs/<pack_id>        Unpublish a pack
"""

import json
import logging
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from quart import Blueprint, jsonify, request, send_file

from trusted_data_agent.auth.middleware import require_auth
from trusted_data_agent.core.agent_pack_manager import AgentPackManager

agent_pack_bp = Blueprint("agent_packs", __name__)
app_logger = logging.getLogger("quart.app")

DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"


def _manager() -> AgentPackManager:
    return AgentPackManager(db_path=str(DB_PATH))


def _has_tool_profiles(cursor, installation_id: int) -> bool:
    """Check if an agent pack installation contains tool_enabled profiles."""
    cursor.execute(
        "SELECT manifest_json FROM agent_pack_installations WHERE id = ?",
        (installation_id,),
    )
    row = cursor.fetchone()
    if not row or not row["manifest_json"]:
        return False
    try:
        manifest = json.loads(row["manifest_json"])
        profiles = manifest.get("profiles", [])
        return any(
            p.get("profile_type") == "tool_enabled" or p.get("requires_mcp")
            for p in profiles
        )
    except (json.JSONDecodeError, TypeError):
        return False


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
    """List installed agent packs for the current user.

    Extends each pack with marketplace_pack_id if published.
    """
    user_uuid = current_user.id

    try:
        manager = _manager()
        packs = await manager.list_packs(user_uuid)

        # Enrich with marketplace_pack_id and sharing_count
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Check which packs are published to marketplace
            cursor.execute(
                "SELECT id, source_installation_id FROM marketplace_agent_packs "
                "WHERE publisher_user_id = ?",
                (user_uuid,)
            )
            published = {row["source_installation_id"]: row["id"] for row in cursor.fetchall()}

            # Get sharing counts by installation_id (grants use installation_id as resource_id)
            installation_ids = [str(p["installation_id"]) for p in packs]
            sharing_counts = {}
            if installation_ids:
                placeholders = ",".join("?" * len(installation_ids))
                cursor.execute(
                    f"SELECT resource_id, COUNT(*) as cnt FROM marketplace_sharing_grants "
                    f"WHERE resource_type = 'agent_pack' AND resource_id IN ({placeholders}) "
                    f"GROUP BY resource_id",
                    installation_ids,
                )
                sharing_counts = {row["resource_id"]: row["cnt"] for row in cursor.fetchall()}

            for pack in packs:
                mp_id = published.get(pack["installation_id"])
                pack["marketplace_pack_id"] = mp_id
                pack["sharing_count"] = sharing_counts.get(str(pack["installation_id"]), 0)

            # ── Include packs shared WITH the current user ──
            cursor.execute(
                "SELECT g.resource_id, g.grantor_user_id, u.username AS shared_by_username, "
                "u.display_name AS shared_by_display_name "
                "FROM marketplace_sharing_grants g "
                "JOIN users u ON g.grantor_user_id = u.id "
                "WHERE g.resource_type = 'agent_pack' AND g.grantee_user_id = ?",
                (user_uuid,),
            )
            shared_grants = cursor.fetchall()

            for grant in shared_grants:
                inst_id = int(grant["resource_id"])
                # Fetch source pack details from installations table
                cursor.execute(
                    "SELECT * FROM agent_pack_installations WHERE id = ?",
                    (inst_id,),
                )
                source_pack = cursor.fetchone()
                if not source_pack:
                    continue

                # Count resources
                cursor.execute(
                    "SELECT resource_type, COUNT(*) as cnt "
                    "FROM agent_pack_resources WHERE pack_installation_id = ? "
                    "GROUP BY resource_type",
                    (inst_id,),
                )
                counts = {r["resource_type"]: r["cnt"] for r in cursor.fetchall()}

                shared_pack = {
                    "installation_id": source_pack["id"],
                    "name": source_pack["name"],
                    "description": source_pack["description"],
                    "version": source_pack["version"],
                    "author": source_pack["author"],
                    "pack_type": source_pack["pack_type"] or "genie",
                    "coordinator_tag": source_pack["coordinator_tag"],
                    "profile_count": counts.get("profile", 0),
                    "collection_count": counts.get("collection", 0),
                    "installed_at": source_pack["installed_at"],
                    "shared_with_me": True,
                    "is_readonly": True,
                    "shared_by_username": grant["shared_by_display_name"] or grant["shared_by_username"],
                    "marketplace_pack_id": None,
                    "sharing_count": 0,
                }
                packs.append(shared_pack)

            conn.close()
        except Exception as e:
            # Table may not exist yet on first bootstrap
            app_logger.debug(f"Agent pack enrichment skipped: {e}")

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


# ══════════════════════════════════════════════════════════════════════════════
# MARKETPLACE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════


# ── Publish ──────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/agent-packs/<int:installation_id>/publish", methods=["POST"])
@require_auth
async def publish_agent_pack(current_user, installation_id: int):
    """Publish an installed agent pack to the marketplace (metadata only, no file export).

    Body (JSON): {"visibility": "public"} — optional, defaults to 'public'.
    """
    user_uuid = current_user.id

    try:
        data = (await request.get_json()) or {}
        visibility = data.get("visibility", "public")

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Verify ownership
        cursor.execute(
            "SELECT * FROM agent_pack_installations WHERE id = ? AND owner_user_id = ?",
            (installation_id, user_uuid),
        )
        pack_row = cursor.fetchone()
        if not pack_row:
            conn.close()
            return jsonify({"status": "error", "message": "Agent pack not found or not owned by you"}), 404

        # Check if already published
        cursor.execute(
            "SELECT id FROM marketplace_agent_packs WHERE source_installation_id = ? AND publisher_user_id = ?",
            (installation_id, user_uuid),
        )
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return jsonify({"status": "error", "message": "This pack is already published", "marketplace_pack_id": existing["id"]}), 409

        # Count resources
        cursor.execute(
            "SELECT resource_type, COUNT(*) as cnt FROM agent_pack_resources WHERE pack_installation_id = ? GROUP BY resource_type",
            (installation_id,),
        )
        counts = {row["resource_type"]: row["cnt"] for row in cursor.fetchall()}
        profile_count = counts.get("profile", 0)
        collection_count = counts.get("collection", 0)

        # Collect profile tags
        cursor.execute(
            "SELECT resource_tag FROM agent_pack_resources WHERE pack_installation_id = ? AND resource_type = 'profile' AND resource_tag IS NOT NULL",
            (installation_id,),
        )
        profile_tags = [row["resource_tag"] for row in cursor.fetchall()]

        # Detect tool_enabled profiles from installation manifest
        has_tool = _has_tool_profiles(cursor, installation_id)

        conn.close()

        # Build manifest summary for preview
        manifest_summary = {
            "name": pack_row["name"],
            "version": pack_row["version"],
            "author": pack_row["author"],
            "pack_type": pack_row["pack_type"] or "genie",
            "profile_count": profile_count,
            "collection_count": collection_count,
            "coordinator_tag": pack_row["coordinator_tag"],
            "profile_tags": profile_tags,
            "has_tool_profiles": has_tool,
        }

        # Insert lightweight marketplace record (no file export)
        marketplace_pack_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            """INSERT INTO marketplace_agent_packs
               (id, name, description, version, author, pack_type, publisher_user_id,
                source_installation_id, profile_count, collection_count, coordinator_tag,
                profile_tags, manifest_summary, file_path, file_size_bytes, visibility,
                download_count, install_count, published_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
            (
                marketplace_pack_id, pack_row["name"], pack_row["description"],
                pack_row["version"], pack_row["author"],
                pack_row["pack_type"] or "genie", user_uuid, installation_id,
                profile_count, collection_count, pack_row["coordinator_tag"],
                json.dumps(profile_tags), json.dumps(manifest_summary),
                "", 0, visibility, now, now,
            ),
        )
        conn.commit()
        conn.close()

        app_logger.info(f"Agent pack '{pack_row['name']}' published to marketplace (id={marketplace_pack_id})")
        return jsonify({
            "status": "success",
            "marketplace_pack_id": marketplace_pack_id,
            "message": "Pack published to marketplace",
        }), 200

    except Exception as e:
        app_logger.error(f"Agent pack publish failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Publish failed: {e}"}), 500


# ── Unpublish ────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/marketplace/agent-packs/<pack_id>", methods=["DELETE"])
@require_auth
async def unpublish_agent_pack(current_user, pack_id: str):
    """Unpublish an agent pack from the marketplace (owner only)."""
    user_uuid = current_user.id

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, publisher_user_id, source_installation_id, name FROM marketplace_agent_packs WHERE id = ?",
            (pack_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "message": "Marketplace pack not found"}), 404

        if row["publisher_user_id"] != user_uuid:
            conn.close()
            return jsonify({"status": "error", "message": "Only the publisher can unpublish"}), 403

        # Delete sharing grants (grants use installation_id as resource_id)
        source_inst_id = str(row["source_installation_id"])
        cursor.execute(
            "DELETE FROM marketplace_sharing_grants WHERE resource_type = 'agent_pack' AND resource_id = ?",
            (source_inst_id,),
        )
        # Delete ratings
        cursor.execute("DELETE FROM agent_pack_ratings WHERE pack_id = ?", (pack_id,))
        # Delete marketplace record
        cursor.execute("DELETE FROM marketplace_agent_packs WHERE id = ?", (pack_id,))
        conn.commit()
        conn.close()

        app_logger.info(f"Agent pack '{row['name']}' unpublished from marketplace (id={pack_id})")
        return jsonify({"status": "success", "message": "Pack unpublished from marketplace"}), 200

    except Exception as e:
        app_logger.error(f"Agent pack unpublish failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Unpublish failed: {e}"}), 500


# ── Browse ───────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/marketplace/agent-packs", methods=["GET"])
@require_auth
async def browse_marketplace_agent_packs(current_user):
    """Browse published agent packs with pagination, search, and sorting.

    Query params: page, per_page, search, sort_by, pack_type, visibility
    """
    user_uuid = current_user.id

    try:
        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("per_page", 12)), 50)
        search = request.args.get("search", "").strip()
        sort_by = request.args.get("sort_by", "recent")
        pack_type = request.args.get("pack_type", "all")
        visibility = request.args.get("visibility", "public")

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row

        # Build query — browse only shows publicly published packs
        # (shared packs appear in My Assets > Agent Packs instead)
        where_clauses = [
            "p.visibility = ?"
        ]
        params = [visibility]

        if pack_type != "all":
            where_clauses.append("p.pack_type = ?")
            params.append(pack_type)

        if search:
            where_clauses.append("(p.name LIKE ? OR p.description LIKE ? OR p.coordinator_tag LIKE ? OR p.profile_tags LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like, like])

        where_sql = " AND ".join(where_clauses)

        # Sort
        sort_map = {
            "downloads": "p.download_count DESC",
            "installs": "p.install_count DESC",
            "rating": "avg_rating DESC",
            "recent": "p.published_at DESC",
        }
        order_sql = sort_map.get(sort_by, "p.published_at DESC")

        # Count total
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM marketplace_agent_packs p WHERE {where_sql}", params)
        total = cursor.fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)

        # Fetch page with ratings JOIN
        offset = (page - 1) * per_page
        query = f"""
            SELECT p.*,
                   u.username AS publisher_username,
                   u.display_name AS publisher_display_name,
                   u.email AS publisher_email,
                   u.marketplace_visible,
                   COALESCE(r.avg_rating, 0) AS avg_rating,
                   COALESCE(r.rating_count, 0) AS rating_count
            FROM marketplace_agent_packs p
            LEFT JOIN users u ON p.publisher_user_id = u.id
            LEFT JOIN (
                SELECT pack_id, AVG(rating) AS avg_rating, COUNT(*) AS rating_count
                FROM agent_pack_ratings
                GROUP BY pack_id
            ) r ON r.pack_id = p.id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, params + [per_page, offset])
        rows = cursor.fetchall()

        packs = []
        for row in rows:
            # Detect tool_enabled profiles from manifest or source installation
            manifest = json.loads(row["manifest_summary"]) if row["manifest_summary"] else {}
            has_tool = manifest.get("has_tool_profiles")
            if has_tool is None and row["source_installation_id"]:
                has_tool = _has_tool_profiles(cursor, row["source_installation_id"])

            pack = {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "version": row["version"],
                "author": row["author"],
                "pack_type": row["pack_type"],
                "publisher_username": row["publisher_display_name"] or row["publisher_username"],
                "publisher_email": row["publisher_email"] if row["marketplace_visible"] else None,
                "profile_count": row["profile_count"],
                "collection_count": row["collection_count"],
                "coordinator_tag": row["coordinator_tag"],
                "profile_tags": json.loads(row["profile_tags"]) if row["profile_tags"] else [],
                "download_count": row["download_count"],
                "install_count": row["install_count"],
                "average_rating": round(row["avg_rating"], 1),
                "rating_count": row["rating_count"],
                "visibility": row["visibility"],
                "published_at": row["published_at"],
                "is_publisher": row["publisher_user_id"] == user_uuid,
                "has_tool_profiles": bool(has_tool),
            }
            packs.append(pack)

        conn.close()

        return jsonify({
            "status": "success",
            "packs": packs,
            "total": total,
            "total_pages": total_pages,
            "page": page,
        }), 200

    except Exception as e:
        app_logger.error(f"Failed to browse marketplace agent packs: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Browse failed: {e}"}), 500


# ── Details ──────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/marketplace/agent-packs/<pack_id>", methods=["GET"])
@require_auth
async def get_marketplace_agent_pack_details(current_user, pack_id: str):
    """Get full details of a marketplace agent pack including manifest summary."""
    user_uuid = current_user.id

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """SELECT p.*,
                      u.username AS publisher_username,
                      u.display_name AS publisher_display_name,
                      u.email AS publisher_email,
                      u.marketplace_visible
               FROM marketplace_agent_packs p
               LEFT JOIN users u ON p.publisher_user_id = u.id
               WHERE p.id = ?""",
            (pack_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "message": "Pack not found"}), 404

        # Get ratings
        cursor.execute(
            "SELECT AVG(rating) AS avg_rating, COUNT(*) AS rating_count FROM agent_pack_ratings WHERE pack_id = ?",
            (pack_id,),
        )
        rating_row = cursor.fetchone()

        # Detect tool_enabled profiles
        manifest = json.loads(row["manifest_summary"]) if row["manifest_summary"] else {}
        has_tool = manifest.get("has_tool_profiles")
        if has_tool is None and row["source_installation_id"]:
            has_tool = _has_tool_profiles(cursor, row["source_installation_id"])

        conn.close()

        result = {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "version": row["version"],
            "author": row["author"],
            "pack_type": row["pack_type"],
            "publisher_username": row["publisher_display_name"] or row["publisher_username"],
            "publisher_email": row["publisher_email"] if row["marketplace_visible"] else None,
            "profile_count": row["profile_count"],
            "collection_count": row["collection_count"],
            "coordinator_tag": row["coordinator_tag"],
            "profile_tags": json.loads(row["profile_tags"]) if row["profile_tags"] else [],
            "manifest_summary": json.loads(row["manifest_summary"]) if row["manifest_summary"] else None,
            "download_count": row["download_count"],
            "install_count": row["install_count"],
            "average_rating": round(rating_row["avg_rating"], 1) if rating_row["avg_rating"] else 0,
            "rating_count": rating_row["rating_count"] or 0,
            "visibility": row["visibility"],
            "published_at": row["published_at"],
            "is_publisher": row["publisher_user_id"] == user_uuid,
            "has_tool_profiles": bool(has_tool),
        }

        return jsonify({"status": "success", **result}), 200

    except Exception as e:
        app_logger.error(f"Failed to get marketplace pack details: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to get details: {e}"}), 500


# ── Install from Marketplace ─────────────────────────────────────────────────

@agent_pack_bp.route("/v1/marketplace/agent-packs/<pack_id>/install", methods=["POST"])
@require_auth
async def subscribe_marketplace_agent_pack(current_user, pack_id: str):
    """Subscribe to a marketplace agent pack (logical sharing grant, no file import)."""
    user_uuid = current_user.id

    try:
        # Find marketplace pack
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, source_installation_id, publisher_user_id FROM marketplace_agent_packs WHERE id = ?",
            (pack_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "message": "Marketplace pack not found"}), 404

        publisher_user_id = row["publisher_user_id"]
        source_installation_id = row["source_installation_id"]
        pack_name = row["name"]
        conn.close()

        # Cannot subscribe to own pack
        if publisher_user_id == user_uuid:
            return jsonify({"status": "error", "message": "Cannot subscribe to your own pack"}), 400

        # Create a sharing grant (logical access)
        from trusted_data_agent.auth.database import get_db_session
        from trusted_data_agent.auth.models import MarketplaceSharingGrant

        with get_db_session() as session:
            # Check for existing grant
            existing_grant = session.query(MarketplaceSharingGrant).filter_by(
                resource_type="agent_pack",
                resource_id=str(source_installation_id),
                grantee_user_id=user_uuid,
            ).first()
            if existing_grant:
                return jsonify({"status": "error", "message": "Already subscribed to this pack"}), 409

            grant = MarketplaceSharingGrant(
                resource_type="agent_pack",
                resource_id=str(source_installation_id),
                grantor_user_id=publisher_user_id,
                grantee_user_id=user_uuid,
            )
            session.add(grant)

        # Increment install_count (subscriber count)
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "UPDATE marketplace_agent_packs SET install_count = install_count + 1, updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), pack_id),
        )
        conn.commit()
        conn.close()

        app_logger.info(f"User {user_uuid} subscribed to marketplace agent pack '{pack_name}' (pack_id={pack_id})")
        return jsonify({
            "status": "success",
            "message": f"Subscribed to {pack_name}",
            "name": pack_name,
        }), 200

    except Exception as e:
        app_logger.error(f"Marketplace agent pack subscribe failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Subscribe failed: {e}"}), 500


# ── Rate ─────────────────────────────────────────────────────────────────────

@agent_pack_bp.route("/v1/marketplace/agent-packs/<pack_id>/rate", methods=["POST"])
@require_auth
async def rate_marketplace_agent_pack(current_user, pack_id: str):
    """Rate a marketplace agent pack.

    Body (JSON): {"rating": 5, "comment": "Excellent pack!"}
    """
    user_uuid = current_user.id

    try:
        data = await request.get_json()
        if not data or "rating" not in data:
            return jsonify({"status": "error", "message": "rating is required"}), 400

        rating = int(data["rating"])
        if rating < 1 or rating > 5:
            return jsonify({"status": "error", "message": "rating must be between 1 and 5"}), 400

        comment = data.get("comment", "").strip() or None

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Verify pack exists
        cursor.execute("SELECT id, publisher_user_id FROM marketplace_agent_packs WHERE id = ?", (pack_id,))
        pack_row = cursor.fetchone()
        if not pack_row:
            conn.close()
            return jsonify({"status": "error", "message": "Pack not found"}), 404

        # Cannot rate own pack
        if pack_row["publisher_user_id"] == user_uuid:
            conn.close()
            return jsonify({"status": "error", "message": "Cannot rate your own pack"}), 400

        # Check existing rating
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "SELECT id FROM agent_pack_ratings WHERE pack_id = ? AND user_id = ?",
            (pack_id, user_uuid),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE agent_pack_ratings SET rating = ?, comment = ?, updated_at = ? WHERE id = ?",
                (rating, comment, now, existing["id"]),
            )
            rating_id = existing["id"]
            message = "Rating updated successfully"
            status_code = 200
        else:
            rating_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO agent_pack_ratings (id, pack_id, user_id, rating, comment, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rating_id, pack_id, user_uuid, rating, comment, now, now),
            )
            message = "Rating submitted successfully"
            status_code = 201

        conn.commit()
        conn.close()

        return jsonify({"status": "success", "rating_id": rating_id, "message": message}), status_code

    except Exception as e:
        app_logger.error(f"Agent pack rating failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Rating failed: {e}"}), 500
