"""
REST API routes for knowledge graph marketplace.

Knowledge graphs represent entity-relationship models (database schemas, business concepts,
domain ontologies) that can be published to and shared via the marketplace.

Marketplace:
- POST /v1/knowledge-graph/<profile_id>/publish    — Publish KG to marketplace
- GET  /v1/marketplace/knowledge-graphs             — Browse marketplace
- GET  /v1/marketplace/knowledge-graphs/<id>        — Detail + ratings
- POST /v1/marketplace/knowledge-graphs/<id>/install — Install into target profile
- POST /v1/marketplace/knowledge-graphs/<id>/fork   — Fork (alias for install)
- POST /v1/marketplace/knowledge-graphs/<id>/rate   — Rate/review
- DELETE /v1/marketplace/knowledge-graphs/<id>      — Unpublish
"""

import hashlib
import json
import logging
import shutil
import sqlite3
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

from quart import Blueprint, jsonify, request

from trusted_data_agent.auth.admin import get_current_user_from_request

kg_marketplace_bp = Blueprint("kg_marketplace", __name__)
app_logger = logging.getLogger("quart.app")

_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"


def _get_user_uuid_from_request():
    """Extract user ID from request (from auth token or header)."""
    user = get_current_user_from_request()
    if user:
        return user.id
    return None


def _get_conn():
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================================
# PUBLISH
# ============================================================================

@kg_marketplace_bp.route("/v1/knowledge-graph/<profile_id>/publish", methods=["POST"])
async def publish_knowledge_graph(profile_id: str):
    """
    Publish a knowledge graph to the marketplace.

    Body (JSON):
    {
        "name": "My KG",
        "description": "...",
        "domain": "finance",
        "version": "1.0.0",
        "author": "...",
        "tags": ["sql", "warehouse"],
        "visibility": "public" | "targeted",
        "user_ids": ["uuid1"]  (required if targeted)
    }
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.kg.settings import is_kg_marketplace_enabled
        if not is_kg_marketplace_enabled():
            return jsonify({"error": "Knowledge graph marketplace has been disabled by the administrator."}), 403

        data = (await request.get_json()) or {}
        visibility = data.get("visibility", "public")
        user_ids = data.get("user_ids", [])
        kg_id_param = (data.get("kg_id") or "").strip() or None

        if visibility not in ("public", "targeted"):
            return jsonify({"error": "Visibility must be 'public' or 'targeted'"}), 400
        if visibility == "targeted" and not user_ids:
            return jsonify({"error": "Targeted publish requires at least one user"}), 400

        # Instantiate the correct KG — use explicit kg_id when provided (multi-KG)
        from components.builtin.knowledge_graph.graph_store import GraphStore
        if kg_id_param:
            store = GraphStore(profile_id, user_uuid, kg_id=kg_id_param)
        else:
            store = GraphStore(profile_id, user_uuid)

        stats = store.get_stats()
        if stats.get("total_entities", 0) == 0:
            return jsonify({"error": "Knowledge graph is empty. Add entities before publishing."}), 400

        conn = _get_conn()
        cursor = conn.cursor()

        # Duplicate check: scoped to specific kg_id if provided, else to profile
        if kg_id_param:
            cursor.execute(
                "SELECT id FROM marketplace_knowledge_graphs WHERE kg_id = ? AND publisher_user_id = ?",
                (kg_id_param, user_uuid),
            )
        else:
            cursor.execute(
                "SELECT id FROM marketplace_knowledge_graphs WHERE source_profile_id = ? AND publisher_user_id = ? AND (kg_id IS NULL OR kg_id = '')",
                (profile_id, user_uuid),
            )
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return jsonify({"error": "This knowledge graph is already published", "marketplace_id": existing["id"]}), 409

        # Export KG data
        entities = store.list_entities(limit=10000)
        relationships = store.list_relationships()

        # Resolve KG metadata (name, description from kg_metadata table)
        kg_meta_name = ""
        kg_meta_description = ""
        kg_meta_database = ""
        try:
            km = store.get_kg_metadata()
            if km:
                kg_meta_name = km.get("name") or ""
                kg_meta_description = km.get("description") or ""
                kg_meta_database = km.get("database_name") or ""
        except Exception:
            pass

        # Build import-ready export with full metadata
        export_data = {
            "export_version": "2.0",
            "kg_id": store.kg_id,
            "kg_name": kg_meta_name,
            "kg_description": kg_meta_description,
            "kg_database_name": kg_meta_database,
            "profile_id": profile_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "entities": entities,
            "relationships": relationships,
        }

        content_hash = hashlib.sha256(
            json.dumps(export_data, sort_keys=True, default=str).encode()
        ).hexdigest()

        # Extract type breakdowns from stats
        entity_types = stats.get("entity_types", {})
        relationship_types = stats.get("relationship_types", {})

        marketplace_id = str(_uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Resolve profile name for fallback
        profile_name = profile_id
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            profiles = config_manager.get_profiles(user_uuid)
            profile = next((p for p in profiles if p.get("id") == profile_id), None)
            if profile:
                profile_name = profile.get("name", profile_id)
        except Exception:
            pass

        name = data.get("name") or kg_meta_name or profile_name
        tags = data.get("tags", [])

        # Build manifest for preview (without full entity/relationship data)
        manifest = {
            "name": name,
            "description": data.get("description", "") or kg_meta_description,
            "domain": data.get("domain", ""),
            "version": data.get("version", "1.0.0"),
            "author": data.get("author", "Unknown"),
            "source_profile_id": profile_id,
            "kg_id": store.kg_id,
            "kg_name": kg_meta_name,
            "kg_database_name": kg_meta_database,
            "entity_count": stats.get("total_entities", 0),
            "relationship_count": stats.get("total_relationships", 0),
            "entity_types": entity_types,
            "relationship_types": relationship_types,
            "tags": tags,
        }

        # Add kg_id column if it exists in the table (safe migration check)
        try:
            cursor.execute("SELECT kg_id FROM marketplace_knowledge_graphs LIMIT 0")
            has_kg_id_col = True
        except Exception:
            has_kg_id_col = False

        if has_kg_id_col:
            cursor.execute(
                """INSERT INTO marketplace_knowledge_graphs
                   (id, source_profile_id, kg_id, name, description, version, author,
                    domain, entity_count, relationship_count,
                    entity_types_json, relationship_types_json, tags_json,
                    publisher_user_id, visibility, manifest_json, content_hash,
                    download_count, install_count, published_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
                (
                    marketplace_id, profile_id, store.kg_id,
                    name,
                    data.get("description", "") or kg_meta_description,
                    data.get("version", "1.0.0"),
                    data.get("author", "Unknown"),
                    data.get("domain", ""),
                    stats.get("total_entities", 0),
                    stats.get("total_relationships", 0),
                    json.dumps(entity_types),
                    json.dumps(relationship_types),
                    json.dumps(tags),
                    user_uuid, visibility,
                    json.dumps(manifest), content_hash,
                    now, now,
                ),
            )
        else:
            cursor.execute(
                """INSERT INTO marketplace_knowledge_graphs
                   (id, source_profile_id, name, description, version, author,
                    domain, entity_count, relationship_count,
                    entity_types_json, relationship_types_json, tags_json,
                    publisher_user_id, visibility, manifest_json, content_hash,
                    download_count, install_count, published_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
                (
                    marketplace_id, profile_id,
                    name,
                    data.get("description", "") or kg_meta_description,
                    data.get("version", "1.0.0"),
                    data.get("author", "Unknown"),
                    data.get("domain", ""),
                    stats.get("total_entities", 0),
                    stats.get("total_relationships", 0),
                    json.dumps(entity_types),
                    json.dumps(relationship_types),
                    json.dumps(tags),
                    user_uuid, visibility,
                    json.dumps(manifest), content_hash,
                    now, now,
                ),
            )

        # Store export files
        marketplace_data = Path(__file__).resolve().parents[3] / "marketplace_data" / "knowledge_graphs" / marketplace_id
        marketplace_data.mkdir(parents=True, exist_ok=True)
        (marketplace_data / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (marketplace_data / "kg_export.json").write_text(json.dumps(export_data, indent=2, default=str), encoding="utf-8")

        # Targeted sharing grants
        if visibility == "targeted" and user_ids:
            for uid in user_ids:
                cursor.execute(
                    "INSERT OR IGNORE INTO marketplace_sharing_grants "
                    "(id, resource_type, resource_id, grantor_user_id, grantee_user_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(_uuid.uuid4()), "knowledge_graph", marketplace_id, user_uuid, uid, now),
                )

        conn.commit()
        conn.close()

        app_logger.info(f"Knowledge graph published from profile '{profile_id}' (id={marketplace_id}, visibility={visibility})")
        return jsonify({
            "status": "success",
            "marketplace_id": marketplace_id,
            "message": "Knowledge graph published to marketplace",
        }), 200

    except Exception as e:
        app_logger.error(f"Knowledge graph publish failed: {e}", exc_info=True)
        return jsonify({"error": f"Publish failed: {e}"}), 500


# ============================================================================
# BROWSE
# ============================================================================

@kg_marketplace_bp.route("/v1/marketplace/knowledge-graphs", methods=["GET"])
async def browse_marketplace_knowledge_graphs():
    """
    Browse published knowledge graphs with pagination, search, and sorting.

    Query params: page, per_page, search, sort_by, domain
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("per_page", 12)), 50)
        search = request.args.get("search", "").strip()
        sort_by = request.args.get("sort_by", "recent")
        domain_filter = request.args.get("domain", "all")

        conn = _get_conn()

        where_clauses = [
            "(kg.visibility = 'public' OR (kg.visibility = 'targeted' AND kg.id IN "
            "(SELECT resource_id FROM marketplace_sharing_grants WHERE resource_type = 'knowledge_graph' AND grantee_user_id = ?)))"
        ]
        params = [user_uuid]

        if domain_filter != "all":
            where_clauses.append("kg.domain = ?")
            params.append(domain_filter)

        if search:
            where_clauses.append("(kg.name LIKE ? OR kg.description LIKE ? OR kg.domain LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])

        where_sql = " AND ".join(where_clauses)

        sort_map = {
            "downloads": "kg.download_count DESC",
            "installs": "kg.install_count DESC",
            "rating": "avg_rating DESC",
            "recent": "kg.published_at DESC",
            "name": "kg.name ASC",
        }
        order_sql = sort_map.get(sort_by, "kg.published_at DESC")

        cursor = conn.cursor()

        # Total count
        cursor.execute(f"SELECT COUNT(*) FROM marketplace_knowledge_graphs kg WHERE {where_sql}", params)
        total = cursor.fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)

        # Fetch page with ratings JOIN
        offset = (page - 1) * per_page
        query = f"""
            SELECT kg.*,
                   u.username AS publisher_username,
                   u.display_name AS publisher_display_name,
                   COALESCE(r.avg_rating, 0) AS avg_rating,
                   COALESCE(r.rating_count, 0) AS rating_count
            FROM marketplace_knowledge_graphs kg
            LEFT JOIN users u ON kg.publisher_user_id = u.id
            LEFT JOIN (
                SELECT kg_marketplace_id, AVG(rating) AS avg_rating, COUNT(*) AS rating_count
                FROM knowledge_graph_ratings
                GROUP BY kg_marketplace_id
            ) r ON r.kg_marketplace_id = kg.id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, params + [per_page, offset])
        rows = cursor.fetchall()

        knowledge_graphs = []
        for row in rows:
            kg = {
                "id": row["id"],
                "source_profile_id": row["source_profile_id"],
                "name": row["name"],
                "description": row["description"],
                "version": row["version"],
                "author": row["author"],
                "domain": row["domain"],
                "entity_count": row["entity_count"],
                "relationship_count": row["relationship_count"],
                "entity_types": json.loads(row["entity_types_json"]) if row["entity_types_json"] else {},
                "relationship_types": json.loads(row["relationship_types_json"]) if row["relationship_types_json"] else {},
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
            knowledge_graphs.append(kg)

        conn.close()

        return jsonify({
            "status": "success",
            "knowledge_graphs": knowledge_graphs,
            "total": total,
            "total_pages": total_pages,
            "page": page,
            "per_page": per_page,
        }), 200

    except Exception as e:
        app_logger.error(f"Browse marketplace knowledge graphs failed: {e}", exc_info=True)
        return jsonify({"error": f"Browse failed: {e}"}), 500


# ============================================================================
# DETAIL
# ============================================================================

@kg_marketplace_bp.route("/v1/marketplace/knowledge-graphs/<marketplace_id>", methods=["GET"])
async def get_marketplace_kg_detail(marketplace_id: str):
    """Get detail for a single marketplace knowledge graph."""
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        conn = _get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """SELECT kg.*,
                      u.username AS publisher_username,
                      u.display_name AS publisher_display_name,
                      COALESCE(r.avg_rating, 0) AS avg_rating,
                      COALESCE(r.rating_count, 0) AS rating_count
               FROM marketplace_knowledge_graphs kg
               LEFT JOIN users u ON kg.publisher_user_id = u.id
               LEFT JOIN (
                   SELECT kg_marketplace_id, AVG(rating) AS avg_rating, COUNT(*) AS rating_count
                   FROM knowledge_graph_ratings GROUP BY kg_marketplace_id
               ) r ON r.kg_marketplace_id = kg.id
               WHERE kg.id = ?""",
            (marketplace_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Knowledge graph not found"}), 404

        # Get user's own rating
        cursor.execute(
            "SELECT rating, comment FROM knowledge_graph_ratings WHERE kg_marketplace_id = ? AND user_id = ?",
            (marketplace_id, user_uuid),
        )
        user_rating_row = cursor.fetchone()

        conn.close()

        kg = {
            "id": row["id"],
            "source_profile_id": row["source_profile_id"],
            "name": row["name"],
            "description": row["description"],
            "version": row["version"],
            "author": row["author"],
            "domain": row["domain"],
            "entity_count": row["entity_count"],
            "relationship_count": row["relationship_count"],
            "entity_types": json.loads(row["entity_types_json"]) if row["entity_types_json"] else {},
            "relationship_types": json.loads(row["relationship_types_json"]) if row["relationship_types_json"] else {},
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

        return jsonify({"status": "success", "knowledge_graph": kg}), 200

    except Exception as e:
        app_logger.error(f"Get marketplace KG detail failed: {e}", exc_info=True)
        return jsonify({"error": f"Failed to get knowledge graph detail: {e}"}), 500


# ============================================================================
# INSTALL
# ============================================================================

@kg_marketplace_bp.route("/v1/marketplace/knowledge-graphs/<marketplace_id>/install", methods=["POST"])
async def install_marketplace_kg(marketplace_id: str):
    """
    Install a marketplace knowledge graph into the user's target profile.

    Body (JSON): {"target_profile_id": "profile-uuid"}
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.kg.settings import is_kg_marketplace_enabled
        if not is_kg_marketplace_enabled():
            return jsonify({"error": "Knowledge graph marketplace has been disabled by the administrator."}), 403

        data = (await request.get_json()) or {}
        target_profile_id = data.get("target_profile_id")
        if not target_profile_id:
            return jsonify({"error": "target_profile_id is required"}), 400

        conn = _get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM marketplace_knowledge_graphs WHERE id = ?", (marketplace_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Knowledge graph not found in marketplace"}), 404

        # Read exported KG data
        marketplace_data = Path(__file__).resolve().parents[3] / "marketplace_data" / "knowledge_graphs" / marketplace_id
        export_path = marketplace_data / "kg_export.json"
        if not export_path.exists():
            conn.close()
            return jsonify({"error": "Knowledge graph export data not found"}), 404

        export_data = json.loads(export_path.read_text(encoding="utf-8"))
        entities = export_data.get("entities", [])
        relationships = export_data.get("relationships", [])

        # Import into target profile using GraphStore.import_bulk
        import uuid as _uuid_inst
        from components.builtin.knowledge_graph.graph_store import GraphStore

        # Always create a fresh KG — never overwrite an existing one
        new_kg_id = str(_uuid_inst.uuid4())
        store = GraphStore(target_profile_id, user_uuid, kg_id=new_kg_id)

        # Check if the target profile already has an active KG
        _ci = sqlite3.connect(str(_DB_PATH))
        _ci.row_factory = sqlite3.Row
        _has_active = _ci.execute(
            "SELECT 1 FROM kg_metadata WHERE profile_id = ? AND user_uuid = ? AND is_active = 1 LIMIT 1",
            (target_profile_id, user_uuid)
        ).fetchone() is not None
        _ci.close()

        # Register KG metadata before importing so entities are scoped to new_kg_id
        kg_name = export_data.get("kg_name") or row["name"]
        kg_description = export_data.get("kg_description") or ""
        kg_database_name = export_data.get("kg_database_name") or ""
        store.set_kg_metadata(
            name=kg_name,
            database_name=kg_database_name,
            description=kg_description or None,
            is_active=not _has_active,
        )

        # Set source to 'marketplace' for provenance tracking
        for ent in entities:
            if ent.get("source") not in ("marketplace",):
                ent["source"] = "marketplace"

        result = store.import_bulk(entities, relationships)

        # Increment install_count
        cursor.execute(
            "UPDATE marketplace_knowledge_graphs SET install_count = install_count + 1 WHERE id = ?",
            (marketplace_id,),
        )
        conn.commit()
        conn.close()

        app_logger.info(
            f"User {user_uuid} installed marketplace KG into profile '{target_profile_id}' "
            f"(marketplace_id={marketplace_id}, kg_id={new_kg_id}, entities={result.get('entities_added', 0)}, "
            f"relationships={result.get('relationships_added', 0)})"
        )
        return jsonify({
            "status": "success",
            "message": f"Knowledge graph '{row['name']}' installed successfully",
            "entities_added": result.get("entities_added", 0),
            "relationships_added": result.get("relationships_added", 0),
        }), 200

    except Exception as e:
        app_logger.error(f"Install marketplace KG failed: {e}", exc_info=True)
        return jsonify({"error": f"Install failed: {e}"}), 500


# ============================================================================
# FORK (alias for install, increments download_count)
# ============================================================================

@kg_marketplace_bp.route("/v1/marketplace/knowledge-graphs/<marketplace_id>/fork", methods=["POST"])
async def fork_marketplace_kg(marketplace_id: str):
    """
    Fork a marketplace knowledge graph (deep copy into target profile).

    Body (JSON): {"target_profile_id": "profile-uuid"}
    """
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        from trusted_data_agent.kg.settings import is_kg_marketplace_enabled
        if not is_kg_marketplace_enabled():
            return jsonify({"error": "Knowledge graph marketplace has been disabled by the administrator."}), 403

        data = (await request.get_json()) or {}
        target_profile_id = data.get("target_profile_id")
        if not target_profile_id:
            return jsonify({"error": "target_profile_id is required"}), 400

        conn = _get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM marketplace_knowledge_graphs WHERE id = ?", (marketplace_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Knowledge graph not found in marketplace"}), 404

        # Read exported KG data
        marketplace_data = Path(__file__).resolve().parents[3] / "marketplace_data" / "knowledge_graphs" / marketplace_id
        export_path = marketplace_data / "kg_export.json"
        if not export_path.exists():
            conn.close()
            return jsonify({"error": "Knowledge graph export data not found"}), 404

        export_data = json.loads(export_path.read_text(encoding="utf-8"))
        entities = export_data.get("entities", [])
        relationships = export_data.get("relationships", [])

        import uuid as _uuid_fork
        from components.builtin.knowledge_graph.graph_store import GraphStore

        # Always create a fresh KG — never overwrite an existing one
        new_kg_id = str(_uuid_fork.uuid4())
        store = GraphStore(target_profile_id, user_uuid, kg_id=new_kg_id)

        # Check if the target profile already has an active KG
        _cf = sqlite3.connect(str(_DB_PATH))
        _cf.row_factory = sqlite3.Row
        _has_active_f = _cf.execute(
            "SELECT 1 FROM kg_metadata WHERE profile_id = ? AND user_uuid = ? AND is_active = 1 LIMIT 1",
            (target_profile_id, user_uuid)
        ).fetchone() is not None
        _cf.close()

        # Register KG metadata before importing
        kg_name_f = export_data.get("kg_name") or row["name"]
        kg_description_f = export_data.get("kg_description") or ""
        kg_database_name_f = export_data.get("kg_database_name") or ""
        store.set_kg_metadata(
            name=kg_name_f,
            database_name=kg_database_name_f,
            description=kg_description_f or None,
            is_active=not _has_active_f,
        )

        for ent in entities:
            if ent.get("source") not in ("marketplace",):
                ent["source"] = "marketplace"

        result = store.import_bulk(entities, relationships)

        # Fork increments download_count
        cursor.execute(
            "UPDATE marketplace_knowledge_graphs SET download_count = download_count + 1 WHERE id = ?",
            (marketplace_id,),
        )
        conn.commit()
        conn.close()

        app_logger.info(
            f"User {user_uuid} forked marketplace KG into profile '{target_profile_id}' "
            f"(marketplace_id={marketplace_id}, kg_id={new_kg_id})"
        )
        return jsonify({
            "status": "success",
            "message": f"Knowledge graph '{row['name']}' forked successfully",
            "entities_added": result.get("entities_added", 0),
            "relationships_added": result.get("relationships_added", 0),
        }), 200

    except Exception as e:
        app_logger.error(f"Fork marketplace KG failed: {e}", exc_info=True)
        return jsonify({"error": f"Fork failed: {e}"}), 500


# ============================================================================
# RATE
# ============================================================================

@kg_marketplace_bp.route("/v1/marketplace/knowledge-graphs/<marketplace_id>/rate", methods=["POST"])
async def rate_marketplace_kg(marketplace_id: str):
    """
    Rate a marketplace knowledge graph.

    Body (JSON): {"rating": 5, "comment": "Excellent schema coverage!"}
    """
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

        conn = _get_conn()
        cursor = conn.cursor()

        # Verify KG exists
        cursor.execute(
            "SELECT id, publisher_user_id FROM marketplace_knowledge_graphs WHERE id = ?",
            (marketplace_id,),
        )
        kg_row = cursor.fetchone()
        if not kg_row:
            conn.close()
            return jsonify({"error": "Knowledge graph not found"}), 404

        # Cannot rate own KG
        if kg_row["publisher_user_id"] == user_uuid:
            conn.close()
            return jsonify({"error": "Cannot rate your own knowledge graph"}), 400

        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "SELECT id FROM knowledge_graph_ratings WHERE kg_marketplace_id = ? AND user_id = ?",
            (marketplace_id, user_uuid),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE knowledge_graph_ratings SET rating = ?, comment = ?, updated_at = ? WHERE id = ?",
                (rating, comment, now, existing["id"]),
            )
            rating_id = existing["id"]
            message = "Rating updated successfully"
            status_code = 200
        else:
            rating_id = str(_uuid.uuid4())
            cursor.execute(
                "INSERT INTO knowledge_graph_ratings (id, kg_marketplace_id, user_id, rating, comment, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rating_id, marketplace_id, user_uuid, rating, comment, now, now),
            )
            message = "Rating submitted successfully"
            status_code = 201

        conn.commit()
        conn.close()

        return jsonify({"status": "success", "rating_id": rating_id, "message": message}), status_code

    except Exception as e:
        app_logger.error(f"KG rating failed: {e}", exc_info=True)
        return jsonify({"error": f"Rating failed: {e}"}), 500


# ============================================================================
# UNPUBLISH
# ============================================================================

@kg_marketplace_bp.route("/v1/marketplace/knowledge-graphs/<marketplace_id>", methods=["DELETE"])
async def unpublish_knowledge_graph(marketplace_id: str):
    """Unpublish a knowledge graph from the marketplace (publisher only)."""
    try:
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"error": "Authentication required"}), 401

        conn = _get_conn()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, name FROM marketplace_knowledge_graphs WHERE id = ? AND publisher_user_id = ?",
            (marketplace_id, user_uuid),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Knowledge graph not found or you are not the publisher"}), 404

        # Delete sharing grants
        cursor.execute(
            "DELETE FROM marketplace_sharing_grants WHERE resource_type = 'knowledge_graph' AND resource_id = ?",
            (marketplace_id,),
        )
        # Delete ratings
        cursor.execute(
            "DELETE FROM knowledge_graph_ratings WHERE kg_marketplace_id = ?",
            (marketplace_id,),
        )
        # Delete marketplace record
        cursor.execute("DELETE FROM marketplace_knowledge_graphs WHERE id = ?", (marketplace_id,))

        conn.commit()
        conn.close()

        # Clean up marketplace_data files
        marketplace_data = Path(__file__).resolve().parents[3] / "marketplace_data" / "knowledge_graphs" / marketplace_id
        if marketplace_data.exists():
            shutil.rmtree(marketplace_data, ignore_errors=True)

        app_logger.info(f"Knowledge graph '{row['name']}' unpublished from marketplace (id={marketplace_id})")
        return jsonify({"status": "success", "message": "Knowledge graph unpublished"}), 200

    except Exception as e:
        app_logger.error(f"Unpublish KG failed: {e}", exc_info=True)
        return jsonify({"error": f"Unpublish failed: {e}"}), 500
