"""
Agent Pack Manager — orchestrates import, export, uninstall, and listing of agent packs.

Operates at the internal Python API level, reusing the same ConfigManager,
CollectionDatabase, and ChromaDB functions that the existing REST endpoints use.
No REST-to-REST calls, no duplicated logic.
"""

import io
import json
import logging
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

app_logger = logging.getLogger("quart.app")

# Required top-level manifest fields
REQUIRED_MANIFEST_FIELDS = {"format_version", "name", "coordinator", "experts", "collections"}


class AgentPackManager:
    """Manages agent pack install, export, uninstall, and listing."""

    def __init__(self, db_path: str = "tda_auth.db"):
        self.db_path = db_path

    def validate_manifest(self, manifest: dict) -> list[str]:
        """Validate manifest schema. Returns list of error strings (empty = valid)."""
        errors = []

        # Check required top-level fields
        missing = REQUIRED_MANIFEST_FIELDS - set(manifest.keys())
        if missing:
            errors.append(f"Missing required fields: {', '.join(sorted(missing))}")
            return errors  # Can't validate further

        if manifest.get("format_version") != "1.0":
            errors.append(f"Unsupported format_version: {manifest.get('format_version')}")

        # Validate coordinator
        coord = manifest["coordinator"]
        if not coord.get("tag"):
            errors.append("Coordinator must have a 'tag'")
        if coord.get("profile_type") != "genie":
            errors.append("Coordinator must be profile_type 'genie'")

        # Validate experts
        experts = manifest["experts"]
        if not isinstance(experts, list) or len(experts) == 0:
            errors.append("'experts' must be a non-empty list")
        else:
            seen_tags = set()
            for i, expert in enumerate(experts):
                tag = expert.get("tag")
                if not tag:
                    errors.append(f"Expert {i} missing 'tag'")
                elif tag in seen_tags:
                    errors.append(f"Duplicate expert tag: {tag}")
                else:
                    seen_tags.add(tag)

                profile_type = expert.get("profile_type")
                if profile_type not in ("rag_focused", "tool_enabled", "llm_only"):
                    errors.append(f"Expert {i} (@{tag}): invalid profile_type '{profile_type}'")

                # Validate collection_ref exists in collections list
                collection_ref = expert.get("collection_ref")
                if collection_ref:
                    collection_refs = {c["ref"] for c in manifest.get("collections", [])}
                    if collection_ref not in collection_refs:
                        errors.append(f"Expert {i} (@{tag}): collection_ref '{collection_ref}' not found in collections")

        # Validate collections
        collections = manifest["collections"]
        if not isinstance(collections, list):
            errors.append("'collections' must be a list")
        else:
            seen_refs = set()
            for i, coll in enumerate(collections):
                ref = coll.get("ref")
                if not ref:
                    errors.append(f"Collection {i} missing 'ref'")
                elif ref in seen_refs:
                    errors.append(f"Duplicate collection ref: {ref}")
                else:
                    seen_refs.add(ref)

                if not coll.get("file"):
                    errors.append(f"Collection {i} ({ref}): missing 'file'")

                repo_type = coll.get("repository_type")
                if repo_type not in ("knowledge", "planner"):
                    errors.append(f"Collection {i} ({ref}): invalid repository_type '{repo_type}'")

        return errors

    async def import_pack(
        self,
        zip_path: Path,
        user_uuid: str,
        mcp_server_id: str | None = None,
    ) -> dict:
        """Import an agent pack: validate → import collections → create profiles → record.

        Args:
            zip_path: Path to the .agentpack ZIP file.
            user_uuid: Owner user UUID.
            mcp_server_id: MCP server ID for tool_enabled profiles (required if pack has any).

        Returns:
            {
                "installation_id": int,
                "coordinator_tag": str,
                "coordinator_profile_id": str,
                "experts_created": int,
                "collections_created": int,
            }

        Raises:
            ValueError: Validation errors (bad manifest, tag conflicts, missing MCP server).
            RuntimeError: Import failures.
        """
        import shutil
        from trusted_data_agent.core.collection_utils import import_collection_from_zip
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.agent.rag_retriever import get_rag_retriever

        config_manager = get_config_manager()

        temp_dir = tempfile.mkdtemp()
        temp_path = Path(temp_dir)

        try:
            # Step 1: Extract .agentpack ZIP
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(temp_path)

            # Read manifest
            manifest_path = temp_path / "manifest.json"
            if not manifest_path.exists():
                raise ValueError("Invalid agent pack: manifest.json missing")

            with open(manifest_path, 'r') as f:
                manifest = json.load(f)

            # Validate manifest
            errors = self.validate_manifest(manifest)
            if errors:
                raise ValueError(f"Invalid manifest: {'; '.join(errors)}")

            # Step 2: Check for tag conflicts
            existing_profiles = config_manager.get_profiles(user_uuid)
            existing_tags = {p.get("tag") for p in existing_profiles if p.get("tag")}

            coord_tag = manifest["coordinator"]["tag"]
            if coord_tag in existing_tags:
                raise ValueError(f"Tag conflict: coordinator tag '@{coord_tag}' is already in use")

            for expert in manifest["experts"]:
                if expert["tag"] in existing_tags:
                    raise ValueError(f"Tag conflict: expert tag '@{expert['tag']}' is already in use")

            # Step 3: Check if MCP server is needed
            needs_mcp = any(e.get("requires_mcp") for e in manifest["experts"])
            if needs_mcp and not mcp_server_id:
                raise ValueError(
                    "This agent pack contains tool_enabled profiles that require an MCP server. "
                    "Please provide mcp_server_id."
                )

            # Step 4: Get active LLM configuration
            llm_config_id = config_manager.get_active_llm_configuration_id(user_uuid)
            if not llm_config_id:
                # Fallback: use first available
                configs = config_manager.get_llm_configurations(user_uuid)
                if configs:
                    llm_config_id = configs[0].get("id")
            if not llm_config_id:
                raise ValueError("No LLM configuration available. Please add one in Uderia first.")

            # Step 5: Import collections
            app_logger.info(f"Importing {len(manifest['collections'])} collections...")
            ref_to_collection_id = {}

            for coll_entry in manifest["collections"]:
                ref = coll_entry["ref"]
                coll_file = coll_entry["file"]  # e.g., "collections/product_knowledge.zip"
                coll_zip_path = temp_path / coll_file

                if not coll_zip_path.exists():
                    raise ValueError(f"Collection ZIP not found in pack: {coll_file}")

                is_planner = coll_entry.get("repository_type") == "planner"
                coll_mcp = mcp_server_id if is_planner else None

                result = await import_collection_from_zip(
                    zip_path=coll_zip_path,
                    user_uuid=user_uuid,
                    display_name=coll_entry.get("name"),
                    mcp_server_id=coll_mcp,
                    skip_reload=True,  # Reload once at the end
                    populate_knowledge_docs=True,
                )

                ref_to_collection_id[ref] = result["collection_id"]
                app_logger.info(f"  Imported collection '{ref}' -> id={result['collection_id']} ({result['document_count']} docs)")

            # Step 6: Create expert profiles
            app_logger.info(f"Creating {len(manifest['experts'])} expert profiles...")
            created_expert_ids = []

            for expert in manifest["experts"]:
                profile_data = self._build_expert_profile(
                    expert, ref_to_collection_id, llm_config_id, mcp_server_id
                )

                success = config_manager.add_profile(profile_data, user_uuid)
                if not success:
                    raise RuntimeError(f"Failed to create profile @{expert['tag']}")

                created_expert_ids.append(profile_data["id"])
                app_logger.info(f"  Created @{expert['tag']} (id={profile_data['id']})")

            # Step 7: Create coordinator profile
            coord_profile_data = self._build_coordinator_profile(
                manifest["coordinator"], created_expert_ids, llm_config_id
            )

            success = config_manager.add_profile(coord_profile_data, user_uuid)
            if not success:
                raise RuntimeError(f"Failed to create coordinator profile @{coord_tag}")

            coordinator_profile_id = coord_profile_data["id"]
            app_logger.info(f"  Created coordinator @{coord_tag} (id={coordinator_profile_id})")

            # Step 8: Reload retriever once
            retriever = get_rag_retriever()
            if retriever:
                try:
                    retriever.reload_collections_for_mcp_server()
                    app_logger.info("Reloaded RAG collections after agent pack import")
                except Exception as e:
                    app_logger.warning(f"Failed to reload collections: {e}")

            # Step 9: Record installation in database
            installation_id = self._record_installation(
                manifest=manifest,
                coordinator_profile_id=coordinator_profile_id,
                expert_profile_ids=created_expert_ids,
                expert_tags=[e["tag"] for e in manifest["experts"]],
                collection_ids=list(ref_to_collection_id.values()),
                collection_refs=list(ref_to_collection_id.keys()),
                user_uuid=user_uuid,
            )

            result = {
                "installation_id": installation_id,
                "name": manifest["name"],
                "coordinator_tag": coord_tag,
                "coordinator_profile_id": coordinator_profile_id,
                "experts_created": len(created_expert_ids),
                "collections_created": len(ref_to_collection_id),
            }

            app_logger.info(f"Agent pack '{manifest['name']}' installed successfully (id={installation_id})")
            return result

        except (ValueError, RuntimeError):
            raise
        except Exception as e:
            app_logger.error(f"Failed to import agent pack: {e}", exc_info=True)
            raise RuntimeError(f"Failed to import agent pack: {e}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def export_pack(
        self,
        coordinator_profile_id: str,
        user_uuid: str,
    ) -> Path:
        """Export a genie coordinator + sub-profiles + collections as .agentpack.

        Returns: Path to the created .agentpack file.
        """
        import shutil
        from trusted_data_agent.core.collection_utils import export_collection_to_zip
        from trusted_data_agent.core.config_manager import get_config_manager

        config_manager = get_config_manager()

        temp_dir = tempfile.mkdtemp()
        temp_path = Path(temp_dir)

        try:
            # Load coordinator profile
            coordinator = config_manager.get_profile(coordinator_profile_id, user_uuid)
            if not coordinator:
                raise ValueError(f"Profile {coordinator_profile_id} not found")

            if coordinator.get("profile_type") != "genie":
                raise ValueError("Can only export genie (coordinator) profiles as agent packs")

            # Load sub-profiles
            slave_ids = coordinator.get("genieConfig", {}).get("slaveProfiles", [])
            if not slave_ids:
                raise ValueError("Coordinator has no sub-profiles")

            experts = []
            for slave_id in slave_ids:
                profile = config_manager.get_profile(slave_id, user_uuid)
                if profile:
                    experts.append(profile)
                else:
                    app_logger.warning(f"Sub-profile {slave_id} not found, skipping")

            if not experts:
                raise ValueError("No valid sub-profiles found")

            # Export collections and build refs
            collections_dir = temp_path / "collections"
            collections_dir.mkdir()

            manifest_collections = []
            manifest_experts = []
            ref_counter = 0

            for expert in experts:
                collection_ref = None

                # Check if expert has knowledge collections
                knowledge_config = expert.get("knowledgeConfig", {})
                expert_collections = knowledge_config.get("collections", [])

                if expert_collections:
                    coll_info = expert_collections[0]  # Primary collection
                    coll_id = coll_info.get("id")

                    if coll_id:
                        ref_counter += 1
                        ref_name = f"collection_{ref_counter}"
                        safe_ref = ref_name.replace(" ", "_").lower()

                        try:
                            exported_zip = await export_collection_to_zip(
                                collection_id=coll_id,
                                user_uuid=user_uuid,
                                output_path=collections_dir,
                            )

                            # Rename to ref-based name
                            final_name = f"{safe_ref}.zip"
                            final_path = collections_dir / final_name
                            if exported_zip != final_path:
                                exported_zip.rename(final_path)

                            # Get collection metadata for manifest
                            from trusted_data_agent.core.collection_db import CollectionDatabase
                            db = CollectionDatabase()
                            coll_meta = db.get_collection_by_id(coll_id)

                            manifest_collections.append({
                                "ref": safe_ref,
                                "file": f"collections/{final_name}",
                                "name": coll_meta["name"] if coll_meta else coll_info.get("name", ""),
                                "repository_type": coll_meta.get("repository_type", "knowledge") if coll_meta else "knowledge",
                                "description": coll_meta.get("description", "") if coll_meta else "",
                            })

                            collection_ref = safe_ref

                        except Exception as e:
                            app_logger.warning(f"Failed to export collection {coll_id} for @{expert.get('tag')}: {e}")

                # Build expert entry (strip runtime IDs)
                expert_entry = {
                    "tag": expert.get("tag"),
                    "name": expert.get("name"),
                    "description": expert.get("description"),
                    "profile_type": expert.get("profile_type"),
                    "classification_mode": expert.get("classification_mode", "light"),
                }

                if collection_ref:
                    expert_entry["collection_ref"] = collection_ref

                if expert.get("profile_type") == "tool_enabled":
                    expert_entry["requires_mcp"] = True

                # Include knowledgeConfig (without collection IDs)
                if knowledge_config:
                    kc_copy = {k: v for k, v in knowledge_config.items() if k != "collections"}
                    if kc_copy:
                        expert_entry["knowledgeConfig"] = kc_copy

                # Include synthesis prompt override
                synthesis_prompt = knowledge_config.get("synthesisPromptOverride")
                if synthesis_prompt:
                    expert_entry["synthesisPromptOverride"] = synthesis_prompt

                manifest_experts.append(expert_entry)

            # Build coordinator entry (strip runtime IDs)
            genie_config = coordinator.get("genieConfig", {})
            coord_entry = {
                "tag": coordinator.get("tag"),
                "name": coordinator.get("name"),
                "description": coordinator.get("description"),
                "profile_type": "genie",
                "classification_mode": coordinator.get("classification_mode", "light"),
                "genieConfig": {
                    k: v for k, v in genie_config.items()
                    if k != "slaveProfiles"  # Don't export runtime IDs
                },
            }

            # Build manifest
            manifest = {
                "format_version": "1.0",
                "name": coordinator.get("name", "Exported Agent Pack"),
                "description": coordinator.get("description", ""),
                "author": "",
                "version": "1.0.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "tags": [],
                "coordinator": coord_entry,
                "experts": manifest_experts,
                "collections": manifest_collections,
            }

            # Write manifest
            manifest_file = temp_path / "manifest.json"
            with open(manifest_file, 'w') as f:
                json.dump(manifest, f, indent=2)

            # Bundle into .agentpack
            safe_name = coordinator.get("tag", "export").replace(" ", "_")
            agentpack_filename = f"{safe_name}.agentpack"
            agentpack_path = Path(temp_dir) / agentpack_filename

            with zipfile.ZipFile(agentpack_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(manifest_file, "manifest.json")
                for coll_file in collections_dir.rglob("*.zip"):
                    arcname = f"collections/{coll_file.name}"
                    zf.write(coll_file, arcname)

            app_logger.info(f"Exported agent pack to {agentpack_path} ({agentpack_path.stat().st_size / 1024 / 1024:.2f} MB)")
            return agentpack_path

        except (ValueError, RuntimeError):
            raise
        except Exception as e:
            app_logger.error(f"Failed to export agent pack: {e}", exc_info=True)
            raise RuntimeError(f"Failed to export agent pack: {e}")

    async def uninstall_pack(self, installation_id: int, user_uuid: str) -> dict:
        """Remove all resources created by an agent pack.

        Returns: {"profiles_deleted": int, "collections_deleted": int}
        """
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.agent.rag_retriever import get_rag_retriever

        config_manager = get_config_manager()

        # Get installation and resources
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Verify installation exists and is owned by user
            cursor.execute(
                "SELECT id, name, owner_user_id FROM agent_pack_installations WHERE id = ?",
                (installation_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Agent pack installation {installation_id} not found")
            if row[2] != user_uuid:
                raise ValueError("You don't own this agent pack installation")

            pack_name = row[1]

            # Get all resources
            cursor.execute(
                "SELECT resource_type, resource_id, resource_tag, resource_role "
                "FROM agent_pack_resources WHERE pack_installation_id = ?",
                (installation_id,)
            )
            resources = cursor.fetchall()

        finally:
            conn.close()

        # Delete resources: profiles first (coordinator, then experts), then collections
        profiles_deleted = 0
        collections_deleted = 0

        # Sort: coordinator profiles first, then experts, then collections
        profiles = [(rt, rid, rtag, role) for rt, rid, rtag, role in resources if rt == "profile"]
        collections = [(rt, rid, rtag, role) for rt, rid, rtag, role in resources if rt == "collection"]

        # Delete coordinator first
        coordinators = [p for p in profiles if p[3] == "coordinator"]
        experts_list = [p for p in profiles if p[3] == "expert"]

        for _, profile_id, tag, _ in coordinators + experts_list:
            try:
                success = config_manager.remove_profile(profile_id, user_uuid)
                if success:
                    profiles_deleted += 1
                    app_logger.info(f"  Deleted profile @{tag} (id={profile_id})")
                else:
                    app_logger.warning(f"  Profile @{tag} (id={profile_id}) not found or already deleted")
            except Exception as e:
                app_logger.warning(f"  Failed to delete profile @{tag}: {e}")

        # Delete collections
        retriever = get_rag_retriever()
        for _, collection_id_str, _, _ in collections:
            try:
                collection_id = int(collection_id_str)
                if retriever:
                    success = retriever.remove_collection(collection_id, user_id=user_uuid)
                    if success:
                        collections_deleted += 1
                        app_logger.info(f"  Deleted collection id={collection_id}")
                    else:
                        app_logger.warning(f"  Collection id={collection_id} not found or already deleted")
                else:
                    app_logger.warning(f"  RAG retriever not available, cannot delete collection {collection_id}")
            except Exception as e:
                app_logger.warning(f"  Failed to delete collection {collection_id_str}: {e}")

        # Delete installation records
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM agent_pack_resources WHERE pack_installation_id = ?", (installation_id,))
            cursor.execute("DELETE FROM agent_pack_installations WHERE id = ?", (installation_id,))
            conn.commit()
        finally:
            conn.close()

        app_logger.info(f"Uninstalled agent pack '{pack_name}' (id={installation_id}): "
                       f"{profiles_deleted} profiles, {collections_deleted} collections deleted")

        return {
            "profiles_deleted": profiles_deleted,
            "collections_deleted": collections_deleted,
        }

    async def list_packs(self, user_uuid: str) -> list[dict]:
        """List installed agent packs for user."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, description, version, author, coordinator_tag, "
                "coordinator_profile_id, installed_at "
                "FROM agent_pack_installations WHERE owner_user_id = ? "
                "ORDER BY installed_at DESC",
                (user_uuid,)
            )
            rows = cursor.fetchall()

            packs = []
            for row in rows:
                # Count resources
                cursor.execute(
                    "SELECT resource_type, COUNT(*) FROM agent_pack_resources "
                    "WHERE pack_installation_id = ? GROUP BY resource_type",
                    (row["id"],)
                )
                counts = dict(cursor.fetchall())

                packs.append({
                    "installation_id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "version": row["version"],
                    "author": row["author"],
                    "coordinator_tag": row["coordinator_tag"],
                    "coordinator_profile_id": row["coordinator_profile_id"],
                    "experts_count": counts.get("profile", 0) - 1,  # Subtract coordinator
                    "collections_count": counts.get("collection", 0),
                    "installed_at": row["installed_at"],
                })

            return packs
        finally:
            conn.close()

    async def get_pack_details(self, installation_id: int, user_uuid: str) -> dict:
        """Get full details of an installed agent pack."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM agent_pack_installations WHERE id = ? AND owner_user_id = ?",
                (installation_id, user_uuid)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Agent pack installation {installation_id} not found")

            # Get resources
            cursor.execute(
                "SELECT resource_type, resource_id, resource_tag, resource_role "
                "FROM agent_pack_resources WHERE pack_installation_id = ?",
                (installation_id,)
            )
            resources = [dict(r) for r in cursor.fetchall()]

            return {
                "installation_id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "version": row["version"],
                "author": row["author"],
                "coordinator_tag": row["coordinator_tag"],
                "coordinator_profile_id": row["coordinator_profile_id"],
                "installed_at": row["installed_at"],
                "manifest": json.loads(row["manifest_json"]),
                "resources": resources,
            }
        finally:
            conn.close()

    # ---- Internal helpers ----

    def _build_expert_profile(
        self, expert: dict, ref_to_collection_id: dict, llm_config_id: str, mcp_server_id: str | None
    ) -> dict:
        """Build a profile data dict for an expert from manifest."""
        profile_id = f"profile-{uuid.uuid4()}"
        profile_type = expert["profile_type"]

        profile_data = {
            "id": profile_id,
            "tag": expert["tag"],
            "name": expert.get("name", expert["tag"]),
            "description": expert.get("description", ""),
            "profile_type": profile_type,
            "llmConfigurationId": llm_config_id,
            "classification_mode": expert.get("classification_mode", "light"),
            "classification_results": {
                "tools": {},
                "prompts": {},
                "resources": {},
                "last_classified": None,
                "classified_with_mode": None,
            },
        }

        # Handle collection linking
        collection_ref = expert.get("collection_ref")

        if profile_type == "rag_focused" and collection_ref:
            collection_id = ref_to_collection_id.get(collection_ref)
            if collection_id:
                knowledge_config = expert.get("knowledgeConfig", {}).copy()
                knowledge_config["collections"] = [{
                    "id": collection_id,
                    "name": expert.get("collection_ref", ""),
                }]

                # Include synthesis prompt override
                synthesis_prompt = expert.get("synthesisPromptOverride")
                if synthesis_prompt:
                    knowledge_config["synthesisPromptOverride"] = synthesis_prompt

                profile_data["knowledgeConfig"] = knowledge_config

        elif profile_type == "tool_enabled":
            if mcp_server_id:
                profile_data["mcpServerId"] = mcp_server_id
            if collection_ref:
                collection_id = ref_to_collection_id.get(collection_ref)
                if collection_id:
                    profile_data["ragCollections"] = [collection_id]

        return profile_data

    def _build_coordinator_profile(
        self, coordinator: dict, expert_ids: list[str], llm_config_id: str
    ) -> dict:
        """Build a profile data dict for the genie coordinator."""
        profile_id = f"profile-{uuid.uuid4()}"

        genie_config = coordinator.get("genieConfig", {}).copy()
        genie_config["slaveProfiles"] = expert_ids

        return {
            "id": profile_id,
            "tag": coordinator["tag"],
            "name": coordinator.get("name", coordinator["tag"]),
            "description": coordinator.get("description", ""),
            "profile_type": "genie",
            "llmConfigurationId": llm_config_id,
            "classification_mode": coordinator.get("classification_mode", "light"),
            "genieConfig": genie_config,
            "classification_results": {
                "tools": {},
                "prompts": {},
                "resources": {},
                "last_classified": None,
                "classified_with_mode": None,
            },
        }

    def _record_installation(
        self,
        manifest: dict,
        coordinator_profile_id: str,
        expert_profile_ids: list[str],
        expert_tags: list[str],
        collection_ids: list[int],
        collection_refs: list[str],
        user_uuid: str,
    ) -> int:
        """Record the agent pack installation in the database."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()

            cursor.execute("""
                INSERT INTO agent_pack_installations
                (name, description, version, author, coordinator_tag,
                 coordinator_profile_id, owner_user_id, installed_at, manifest_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                manifest["name"],
                manifest.get("description", ""),
                manifest.get("version", "1.0.0"),
                manifest.get("author", ""),
                manifest["coordinator"]["tag"],
                coordinator_profile_id,
                user_uuid,
                now,
                json.dumps(manifest),
            ))

            installation_id = cursor.lastrowid

            # Record coordinator
            cursor.execute("""
                INSERT INTO agent_pack_resources
                (pack_installation_id, resource_type, resource_id, resource_tag, resource_role)
                VALUES (?, 'profile', ?, ?, 'coordinator')
            """, (installation_id, coordinator_profile_id, manifest["coordinator"]["tag"]))

            # Record experts
            for pid, tag in zip(expert_profile_ids, expert_tags):
                cursor.execute("""
                    INSERT INTO agent_pack_resources
                    (pack_installation_id, resource_type, resource_id, resource_tag, resource_role)
                    VALUES (?, 'profile', ?, ?, 'expert')
                """, (installation_id, pid, tag))

            # Record collections
            for coll_id, ref in zip(collection_ids, collection_refs):
                cursor.execute("""
                    INSERT INTO agent_pack_resources
                    (pack_installation_id, resource_type, resource_id, resource_tag, resource_role)
                    VALUES (?, 'collection', ?, ?, 'collection')
                """, (installation_id, str(coll_id), ref))

            conn.commit()
            return installation_id
        finally:
            conn.close()
