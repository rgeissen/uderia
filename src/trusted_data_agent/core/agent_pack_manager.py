"""
Agent Pack Manager — orchestrates import, export, create, uninstall, and listing
of agent packs.

Supports both v1.0 (coordinator + experts) and v1.1 (unified profiles array)
manifest formats. v1.0 manifests are normalised to v1.1 internally before
processing so all code paths are unified.

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

# Valid profile types and roles
VALID_PROFILE_TYPES = {"rag_focused", "tool_enabled", "llm_only", "genie"}
VALID_ROLES = {"coordinator", "expert", "standalone"}


class AgentPackManager:
    """Manages agent pack install, export, create, uninstall, and listing."""

    def __init__(self, db_path: str = "tda_auth.db"):
        self.db_path = db_path

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate_manifest(self, manifest: dict) -> list[str]:
        """Validate manifest schema. Returns list of error strings (empty = valid)."""
        version = manifest.get("format_version")
        if version == "1.0":
            return self._validate_manifest_v10(manifest)
        elif version == "1.1":
            return self._validate_manifest_v11(manifest)
        else:
            return [f"Unsupported format_version: {version}"]

    def _validate_manifest_v10(self, manifest: dict) -> list[str]:
        """Validate v1.0 manifest (coordinator + experts + collections)."""
        errors = []
        required = {"format_version", "name", "coordinator", "experts", "collections"}
        missing = required - set(manifest.keys())
        if missing:
            errors.append(f"Missing required fields: {', '.join(sorted(missing))}")
            return errors

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

    def _validate_manifest_v11(self, manifest: dict) -> list[str]:
        """Validate v1.1 manifest (unified profiles array)."""
        errors = []
        required = {"format_version", "name", "profiles"}
        missing = required - set(manifest.keys())
        if missing:
            errors.append(f"Missing required fields: {', '.join(sorted(missing))}")
            return errors

        profiles = manifest.get("profiles")
        if not isinstance(profiles, list) or len(profiles) == 0:
            errors.append("'profiles' must be a non-empty list")
            return errors

        seen_tags = set()
        all_tags = {p.get("tag") for p in profiles if p.get("tag")}

        for i, prof in enumerate(profiles):
            tag = prof.get("tag")
            if not tag:
                errors.append(f"Profile {i} missing 'tag'")
            elif tag in seen_tags:
                errors.append(f"Duplicate profile tag: {tag}")
            else:
                seen_tags.add(tag)

            profile_type = prof.get("profile_type")
            if profile_type not in VALID_PROFILE_TYPES:
                errors.append(f"Profile {i} (@{tag}): invalid profile_type '{profile_type}'")

            role = prof.get("role")
            if role not in VALID_ROLES:
                errors.append(f"Profile {i} (@{tag}): invalid role '{role}'")

            # Genie profiles must have child_tags
            if profile_type == "genie":
                child_tags = prof.get("child_tags", [])
                if not isinstance(child_tags, list) or len(child_tags) == 0:
                    errors.append(f"Profile {i} (@{tag}): genie profiles must have non-empty 'child_tags'")
                else:
                    for ct in child_tags:
                        if ct not in all_tags:
                            errors.append(f"Profile {i} (@{tag}): child_tag '{ct}' not found in profiles")

            # Validate collection_refs reference existing collections
            collection_refs = prof.get("collection_refs", [])
            if collection_refs:
                manifest_coll_refs = {c.get("ref") for c in manifest.get("collections", [])}
                for cr in collection_refs:
                    if cr not in manifest_coll_refs:
                        errors.append(f"Profile {i} (@{tag}): collection_ref '{cr}' not found in collections")

        # Validate collections (can be empty for llm_only-only packs)
        collections = manifest.get("collections", [])
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

    # ── v1.0 → v1.1 Normaliser ────────────────────────────────────────────────

    def _normalize_v10_to_v11(self, manifest: dict) -> dict:
        """Convert a v1.0 manifest to v1.1 format for unified processing."""
        profiles = []

        # Convert experts
        for expert in manifest.get("experts", []):
            entry = {
                "tag": expert["tag"],
                "name": expert.get("name"),
                "description": expert.get("description"),
                "profile_type": expert["profile_type"],
                "classification_mode": expert.get("classification_mode", "light"),
                "role": "expert",
                "collection_refs": [expert["collection_ref"]] if expert.get("collection_ref") else [],
            }
            if expert.get("requires_mcp"):
                entry["requires_mcp"] = True
            if expert.get("knowledgeConfig"):
                entry["knowledgeConfig"] = expert["knowledgeConfig"]
            if expert.get("synthesisPromptOverride"):
                entry["synthesisPromptOverride"] = expert["synthesisPromptOverride"]
            profiles.append(entry)

        # Convert coordinator
        coord = manifest["coordinator"]
        profiles.append({
            "tag": coord["tag"],
            "name": coord.get("name"),
            "description": coord.get("description"),
            "profile_type": "genie",
            "role": "coordinator",
            "classification_mode": coord.get("classification_mode", "light"),
            "child_tags": [e["tag"] for e in manifest.get("experts", [])],
            "genieConfig": coord.get("genieConfig", {}),
        })

        result = {**manifest, "format_version": "1.1", "profiles": profiles}
        # Remove old keys
        result.pop("coordinator", None)
        result.pop("experts", None)
        return result

    # ── Import ─────────────────────────────────────────────────────────────────

    async def import_pack(
        self,
        zip_path: Path,
        user_uuid: str,
        mcp_server_id: str | None = None,
        llm_configuration_id: str | None = None,
        conflict_strategy: str | None = None,
    ) -> dict:
        """Import an agent pack: validate → import collections → create profiles → record.

        Supports both v1.0 and v1.1 manifest formats (v1.0 is normalised to v1.1).

        Args:
            conflict_strategy: How to handle tag conflicts.
                - None: raise ValueError (default, backward compatible)
                - "replace": delete existing profiles with conflicting tags
                - "expand": auto-rename conflicting tags (e.g. TAG → TAG2)

        Returns:
            {
                "installation_id": int,
                "name": str,
                "coordinator_tag": str | None,
                "coordinator_profile_id": str | None,
                "profiles_created": int,
                "collections_created": int,
                "tag_remap": dict | None,
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

            # Validate manifest (handles both v1.0 and v1.1)
            errors = self.validate_manifest(manifest)
            if errors:
                raise ValueError(f"Invalid manifest: {'; '.join(errors)}")

            # Normalise v1.0 → v1.1 for unified processing
            if manifest.get("format_version") == "1.0":
                manifest = self._normalize_v10_to_v11(manifest)

            profiles = manifest["profiles"]
            collections = manifest.get("collections", [])

            # Step 2: Check for tag conflicts and resolve based on strategy
            existing_profiles = config_manager.get_profiles(user_uuid)
            existing_tags = {p.get("tag") for p in existing_profiles if p.get("tag")}

            conflicting_tags = [
                prof["tag"] for prof in profiles
                if prof["tag"] in existing_tags
            ]

            tag_remap = {}

            if conflicting_tags:
                if conflict_strategy == "replace":
                    # Delete existing profiles with conflicting tags AND their
                    # orphaned collections (cascade cleanup).
                    from trusted_data_agent.agent.rag_retriever import get_rag_retriever
                    from trusted_data_agent.core.agent_pack_db import AgentPackDB

                    retriever = get_rag_retriever()
                    pack_db = AgentPackDB(self.db_path)

                    # Collect all collection IDs referenced by profiles being replaced
                    orphan_collection_ids = set()
                    replaced_profile_ids = []

                    for existing_prof in existing_profiles:
                        if existing_prof.get("tag") not in conflicting_tags:
                            continue

                        replaced_profile_ids.append(existing_prof["id"])

                        # Planner collections (ragCollections: list of int IDs)
                        for cid in existing_prof.get("ragCollections", []):
                            if cid != '*':
                                orphan_collection_ids.add(int(cid))

                        # Knowledge collections (knowledgeConfig.collections: list of {id, name})
                        for kc in existing_prof.get("knowledgeConfig", {}).get("collections", []):
                            if kc.get("id"):
                                orphan_collection_ids.add(int(kc["id"]))

                    # Remove the profiles
                    for existing_prof in existing_profiles:
                        if existing_prof.get("tag") in conflicting_tags:
                            config_manager.remove_profile(existing_prof["id"], user_uuid)
                            app_logger.info(
                                f"  Replaced existing profile @{existing_prof['tag']} "
                                f"(id={existing_prof['id']})"
                            )

                    # After profile removal, check which collections are now orphaned
                    # (not referenced by any remaining profile)
                    if orphan_collection_ids:
                        remaining_profiles = config_manager.get_profiles(user_uuid)
                        still_used_ids = set()
                        for rp in remaining_profiles:
                            for cid in rp.get("ragCollections", []):
                                if cid != '*':
                                    still_used_ids.add(int(cid))
                            for kc in rp.get("knowledgeConfig", {}).get("collections", []):
                                if kc.get("id"):
                                    still_used_ids.add(int(kc["id"]))

                        for coll_id in orphan_collection_ids:
                            if coll_id in still_used_ids:
                                app_logger.info(f"  Kept collection id={coll_id} (still referenced by another profile)")
                                continue
                            # Also check pack-managed status
                            if pack_db.is_pack_managed("collection", str(coll_id)):
                                app_logger.info(f"  Kept collection id={coll_id} (still referenced by another pack)")
                                continue
                            if retriever:
                                try:
                                    success = retriever.remove_collection(coll_id, user_id=user_uuid)
                                    if success:
                                        app_logger.info(f"  Deleted orphaned collection id={coll_id}")
                                    else:
                                        app_logger.warning(f"  Collection id={coll_id} not found or already deleted")
                                except Exception as e:
                                    app_logger.warning(f"  Failed to delete collection {coll_id}: {e}")

                    # Refresh existing_tags after deletions
                    existing_profiles = config_manager.get_profiles(user_uuid)
                    existing_tags = {p.get("tag") for p in existing_profiles if p.get("tag")}

                elif conflict_strategy == "expand":
                    tag_remap = self._compute_tag_expansion(
                        conflicting_tags, existing_tags, profiles
                    )
                    self._apply_tag_remap(profiles, tag_remap)
                    app_logger.info(f"  Tag expansion remap: {tag_remap}")

                else:
                    # Default: raise error (backward compatible)
                    raise ValueError(
                        f"Tag conflict: tags {', '.join('@' + t for t in conflicting_tags)} "
                        f"are already in use"
                    )

            # Step 2b: Deduplicate pack name
            pack_name = manifest["name"]
            existing_pack_names = self._get_existing_pack_names(user_uuid)
            if pack_name in existing_pack_names:
                counter = 2
                while f"{pack_name} ({counter})" in existing_pack_names:
                    counter += 1
                manifest["name"] = f"{pack_name} ({counter})"
                app_logger.info(
                    f"  Pack name '{pack_name}' already exists, "
                    f"renamed to '{manifest['name']}'"
                )

            # Step 3: Check if MCP server is needed
            needs_mcp = any(p.get("requires_mcp") for p in profiles)
            if needs_mcp and not mcp_server_id:
                raise ValueError(
                    "This agent pack contains tool_enabled profiles that require an MCP server. "
                    "Please provide mcp_server_id."
                )

            # Step 4: Resolve LLM configuration
            llm_config_id = llm_configuration_id

            if not llm_config_id:
                llm_config_id = config_manager.get_active_llm_configuration_id(user_uuid)

            if not llm_config_id:
                configs = config_manager.get_llm_configurations(user_uuid)
                if configs:
                    llm_config_id = configs[0].get("id")

            if not llm_config_id:
                raise ValueError("No LLM configuration available. Please add one in Uderia first.")

            all_configs = config_manager.get_llm_configurations(user_uuid)
            if llm_config_id not in {c.get("id") for c in all_configs}:
                raise ValueError(f"LLM configuration '{llm_config_id}' not found. It may have been deleted.")

            # Step 5: Import collections
            app_logger.info(f"Importing {len(collections)} collections...")
            ref_to_collection_id = {}

            for coll_entry in collections:
                ref = coll_entry["ref"]
                coll_file = coll_entry["file"]
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
                    skip_reload=True,
                    populate_knowledge_docs=True,
                )

                ref_to_collection_id[ref] = {
                    "id": result["collection_id"],
                    "name": result["collection_name"],
                }
                app_logger.info(f"  Imported collection '{ref}' -> id={result['collection_id']} ({result['document_count']} docs)")

            # Step 6: Create profiles — non-genie first, then genie (so child IDs are available)
            app_logger.info(f"Creating {len(profiles)} profiles...")

            non_genie = [p for p in profiles if p["profile_type"] != "genie"]
            genie_profiles = [p for p in profiles if p["profile_type"] == "genie"]

            tag_to_profile_id = {}
            created_profile_ids = []

            for prof in non_genie:
                profile_data = self._build_profile(
                    prof, ref_to_collection_id, llm_config_id, mcp_server_id,
                    tag_to_profile_id=tag_to_profile_id,
                )
                success = config_manager.add_profile(profile_data, user_uuid)
                if not success:
                    raise RuntimeError(f"Failed to create profile @{prof['tag']}")

                tag_to_profile_id[prof["tag"]] = profile_data["id"]
                created_profile_ids.append(profile_data["id"])
                app_logger.info(f"  Created @{prof['tag']} (id={profile_data['id']})")

            for prof in genie_profiles:
                profile_data = self._build_profile(
                    prof, ref_to_collection_id, llm_config_id, mcp_server_id,
                    tag_to_profile_id=tag_to_profile_id,
                )
                success = config_manager.add_profile(profile_data, user_uuid)
                if not success:
                    raise RuntimeError(f"Failed to create profile @{prof['tag']}")

                tag_to_profile_id[prof["tag"]] = profile_data["id"]
                created_profile_ids.append(profile_data["id"])
                app_logger.info(f"  Created coordinator @{prof['tag']} (id={profile_data['id']})")

            # Step 7: Reload retriever once
            retriever = get_rag_retriever()
            if retriever:
                try:
                    retriever.reload_collections_for_mcp_server()
                    app_logger.info("Reloaded RAG collections after agent pack import")
                except Exception as e:
                    app_logger.warning(f"Failed to reload collections: {e}")

            # Step 8: Determine pack type and coordinator info
            coordinator_tag = None
            coordinator_profile_id = None
            for prof in genie_profiles:
                if prof["role"] == "coordinator":
                    coordinator_tag = prof["tag"]
                    coordinator_profile_id = tag_to_profile_id.get(prof["tag"])
                    break

            has_genie = len(genie_profiles) > 0
            if has_genie:
                pack_type = "genie"
            elif len(profiles) > 1:
                pack_type = "bundle"
            else:
                pack_type = "single"

            # Step 9: Record installation in database
            profile_tags = [p["tag"] for p in profiles]
            profile_roles = [p["role"] for p in profiles]

            installation_id = self._record_installation(
                manifest=manifest,
                coordinator_tag=coordinator_tag,
                coordinator_profile_id=coordinator_profile_id,
                pack_type=pack_type,
                profile_ids=created_profile_ids,
                profile_tags=profile_tags,
                profile_roles=profile_roles,
                collection_ids=[info["id"] for info in ref_to_collection_id.values()],
                collection_refs=list(ref_to_collection_id.keys()),
                user_uuid=user_uuid,
            )

            result = {
                "installation_id": installation_id,
                "name": manifest["name"],
                "coordinator_tag": coordinator_tag,
                "coordinator_profile_id": coordinator_profile_id,
                "profiles_created": len(created_profile_ids),
                "collections_created": len(ref_to_collection_id),
                # Legacy compat
                "experts_created": len(non_genie),
                "tag_remap": tag_remap if tag_remap else None,
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

    # ── Export (legacy — single coordinator) ───────────────────────────────────

    async def export_pack(
        self,
        coordinator_profile_id: str | None = None,
        user_uuid: str = "",
        profile_ids: list[str] | None = None,
        pack_name: str = "",
        pack_description: str = "",
    ) -> Path:
        """Export profiles + collections as .agentpack (v1.1 manifest).

        Can be called in two ways:
        - Legacy: coordinator_profile_id only (exports genie + children)
        - New: profile_ids list (exports any selection of profiles)

        Returns: Path to the created .agentpack file.
        """
        import shutil
        from trusted_data_agent.core.collection_utils import export_collection_to_zip
        from trusted_data_agent.core.config_manager import get_config_manager

        config_manager = get_config_manager()

        # Resolve profile list
        if profile_ids is None and coordinator_profile_id:
            profile_ids = [coordinator_profile_id]

        if not profile_ids:
            raise ValueError("No profiles specified for export")

        temp_dir = tempfile.mkdtemp()
        temp_path = Path(temp_dir)

        try:
            # Load all selected profiles
            selected_profiles = []
            selected_ids = set(profile_ids)

            for pid in profile_ids:
                profile = config_manager.get_profile(pid, user_uuid)
                if profile:
                    selected_profiles.append(profile)
                else:
                    app_logger.warning(f"Profile {pid} not found, skipping")

            if not selected_profiles:
                raise ValueError("No valid profiles found")

            # Auto-include genie children not already in selection
            for profile in list(selected_profiles):
                if profile.get("profile_type") == "genie":
                    child_ids = profile.get("genieConfig", {}).get("slaveProfiles", [])
                    for child_id in child_ids:
                        if child_id not in selected_ids:
                            child = config_manager.get_profile(child_id, user_uuid)
                            if child:
                                selected_profiles.append(child)
                                selected_ids.add(child_id)
                                app_logger.info(f"  Auto-included child @{child.get('tag')} from genie @{profile.get('tag')}")

            # Build tag set for genie child references
            genie_child_ids = set()
            for profile in selected_profiles:
                if profile.get("profile_type") == "genie":
                    genie_child_ids.update(profile.get("genieConfig", {}).get("slaveProfiles", []))

            # Export collections and build refs
            collections_dir = temp_path / "collections"
            collections_dir.mkdir()

            manifest_collections = []
            manifest_profiles = []
            exported_collection_ids = set()
            ref_counter = 0

            for profile in selected_profiles:
                collection_refs = []

                # Collect collections from knowledgeConfig
                knowledge_config = profile.get("knowledgeConfig", {})
                profile_collections = knowledge_config.get("collections", [])

                for coll_info in profile_collections:
                    coll_id = coll_info.get("id")
                    if not coll_id or coll_id in exported_collection_ids:
                        # Already exported — find existing ref
                        existing_ref = next(
                            (mc["ref"] for mc in manifest_collections if mc.get("_source_id") == coll_id),
                            None
                        )
                        if existing_ref:
                            collection_refs.append(existing_ref)
                        continue

                    ref_counter += 1
                    ref_name = f"collection_{ref_counter}"
                    safe_ref = ref_name.replace(" ", "_").lower()

                    try:
                        exported_zip = await export_collection_to_zip(
                            collection_id=coll_id,
                            user_uuid=user_uuid,
                            output_path=collections_dir,
                        )

                        final_name = f"{safe_ref}.zip"
                        final_path = collections_dir / final_name
                        if exported_zip != final_path:
                            exported_zip.rename(final_path)

                        from trusted_data_agent.core.collection_db import CollectionDatabase
                        db = CollectionDatabase()
                        coll_meta = db.get_collection_by_id(coll_id)

                        manifest_collections.append({
                            "ref": safe_ref,
                            "file": f"collections/{final_name}",
                            "name": coll_meta["name"] if coll_meta else coll_info.get("name", ""),
                            "repository_type": coll_meta.get("repository_type", "knowledge") if coll_meta else "knowledge",
                            "description": coll_meta.get("description", "") if coll_meta else "",
                            "_source_id": coll_id,  # Internal tracking, stripped before writing
                        })

                        collection_refs.append(safe_ref)
                        exported_collection_ids.add(coll_id)

                    except Exception as e:
                        app_logger.warning(f"Failed to export collection {coll_id} for @{profile.get('tag')}: {e}")

                # Also check ragCollections (planner repos on tool_enabled profiles)
                rag_collection_ids = profile.get("ragCollections", [])
                for coll_id in rag_collection_ids:
                    if coll_id in exported_collection_ids:
                        existing_ref = next(
                            (mc["ref"] for mc in manifest_collections if mc.get("_source_id") == coll_id),
                            None
                        )
                        if existing_ref:
                            collection_refs.append(existing_ref)
                        continue

                    ref_counter += 1
                    ref_name = f"collection_{ref_counter}"
                    safe_ref = ref_name.replace(" ", "_").lower()

                    try:
                        exported_zip = await export_collection_to_zip(
                            collection_id=coll_id,
                            user_uuid=user_uuid,
                            output_path=collections_dir,
                        )

                        final_name = f"{safe_ref}.zip"
                        final_path = collections_dir / final_name
                        if exported_zip != final_path:
                            exported_zip.rename(final_path)

                        from trusted_data_agent.core.collection_db import CollectionDatabase
                        db = CollectionDatabase()
                        coll_meta = db.get_collection_by_id(coll_id)

                        manifest_collections.append({
                            "ref": safe_ref,
                            "file": f"collections/{final_name}",
                            "name": coll_meta["name"] if coll_meta else "",
                            "repository_type": coll_meta.get("repository_type", "planner") if coll_meta else "planner",
                            "description": coll_meta.get("description", "") if coll_meta else "",
                            "_source_id": coll_id,
                        })

                        collection_refs.append(safe_ref)
                        exported_collection_ids.add(coll_id)

                    except Exception as e:
                        app_logger.warning(f"Failed to export planner collection {coll_id} for @{profile.get('tag')}: {e}")

                # Determine role
                if profile.get("profile_type") == "genie":
                    role = "coordinator"
                elif profile["id"] in genie_child_ids:
                    role = "expert"
                else:
                    role = "standalone"

                # Build profile entry
                prof_entry = {
                    "tag": profile.get("tag"),
                    "name": profile.get("name"),
                    "description": profile.get("description"),
                    "profile_type": profile.get("profile_type"),
                    "role": role,
                    "classification_mode": profile.get("classification_mode", "light"),
                }

                # Deduplicate collection_refs while preserving order
                if collection_refs:
                    seen = set()
                    deduped = []
                    for cr in collection_refs:
                        if cr not in seen:
                            seen.add(cr)
                            deduped.append(cr)
                    prof_entry["collection_refs"] = deduped

                if profile.get("profile_type") == "genie":
                    # child_tags: tags of children in this pack
                    child_ids = profile.get("genieConfig", {}).get("slaveProfiles", [])
                    child_tags = []
                    for cid in child_ids:
                        child_prof = next((p for p in selected_profiles if p["id"] == cid), None)
                        if child_prof:
                            child_tags.append(child_prof.get("tag"))
                    prof_entry["child_tags"] = child_tags

                    genie_config = profile.get("genieConfig", {})
                    gc_copy = {k: v for k, v in genie_config.items() if k != "slaveProfiles"}
                    if gc_copy:
                        prof_entry["genieConfig"] = gc_copy

                elif profile.get("profile_type") == "tool_enabled":
                    prof_entry["requires_mcp"] = True

                # Include knowledgeConfig (without collection IDs)
                if knowledge_config:
                    kc_copy = {k: v for k, v in knowledge_config.items() if k != "collections"}
                    if kc_copy:
                        prof_entry["knowledgeConfig"] = kc_copy

                # Include synthesis prompt override
                synthesis_prompt = knowledge_config.get("synthesisPromptOverride")
                if synthesis_prompt:
                    prof_entry["synthesisPromptOverride"] = synthesis_prompt

                manifest_profiles.append(prof_entry)

            # Strip internal tracking fields from collections
            for mc in manifest_collections:
                mc.pop("_source_id", None)

            # Determine pack name
            if not pack_name:
                genie_prof = next((p for p in selected_profiles if p.get("profile_type") == "genie"), None)
                pack_name = genie_prof.get("name", "Exported Agent Pack") if genie_prof else "Exported Agent Pack"

            # Build v1.1 manifest
            manifest = {
                "format_version": "1.1",
                "name": pack_name,
                "description": pack_description or "",
                "author": "",
                "version": "1.0.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "tags": [],
                "profiles": manifest_profiles,
                "collections": manifest_collections,
            }

            # Write manifest
            manifest_file = temp_path / "manifest.json"
            with open(manifest_file, 'w') as f:
                json.dump(manifest, f, indent=2)

            # Bundle into .agentpack
            safe_name = (pack_name or "export").replace(" ", "_")[:50]
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

    # ── Uninstall ──────────────────────────────────────────────────────────────

    async def uninstall_pack(self, installation_id: int, user_uuid: str) -> dict:
        """Remove all resources created by an agent pack.

        Uses conditional deletion: only deletes resources that are not
        referenced by any other pack (many-to-many safe).

        Returns: {"profiles_deleted": int, "collections_deleted": int,
                  "profiles_kept": int, "collections_kept": int}
        """
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.agent.rag_retriever import get_rag_retriever
        from trusted_data_agent.core.agent_pack_db import AgentPackDB

        config_manager = get_config_manager()
        pack_db = AgentPackDB(self.db_path)

        # Verify installation exists and is owned by user
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
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
        finally:
            conn.close()

        # Get all resources BEFORE removing junction rows
        resources = pack_db.get_resources_for_pack(installation_id)

        # Step 1: Remove junction rows for THIS pack
        pack_db.remove_pack_resources(installation_id)

        # Step 2: Delete resources that are no longer referenced by ANY pack
        profiles_deleted = 0
        collections_deleted = 0
        profiles_kept = 0
        collections_kept = 0

        # Separate profiles and collections; process profiles first
        profile_resources = [r for r in resources if r["resource_type"] == "profile"]
        collection_resources = [r for r in resources if r["resource_type"] == "collection"]

        # Sort profiles: coordinator first, then others
        coordinators = [r for r in profile_resources if r["resource_role"] == "coordinator"]
        others = [r for r in profile_resources if r["resource_role"] != "coordinator"]

        for res in coordinators + others:
            still_referenced = pack_db.is_pack_managed(res["resource_type"], res["resource_id"])

            if not still_referenced and res.get("is_owned", 1):
                try:
                    success = config_manager.remove_profile(res["resource_id"], user_uuid)
                    if success:
                        profiles_deleted += 1
                        app_logger.info(f"  Deleted profile @{res['resource_tag']} (id={res['resource_id']})")
                    else:
                        app_logger.warning(f"  Profile @{res['resource_tag']} not found or already deleted")
                except Exception as e:
                    app_logger.warning(f"  Failed to delete profile @{res['resource_tag']}: {e}")
            else:
                profiles_kept += 1
                app_logger.info(f"  Kept profile @{res['resource_tag']} (still referenced by another pack)")

        # Delete collections
        retriever = get_rag_retriever()
        for res in collection_resources:
            still_referenced = pack_db.is_pack_managed(res["resource_type"], res["resource_id"])

            if not still_referenced and res.get("is_owned", 1):
                try:
                    collection_id = int(res["resource_id"])
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
                    app_logger.warning(f"  Failed to delete collection {res['resource_id']}: {e}")
            else:
                collections_kept += 1
                app_logger.info(f"  Kept collection {res['resource_id']} (still referenced by another pack)")

        # Step 3: Delete installation record
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM agent_pack_installations WHERE id = ?", (installation_id,))
            conn.commit()
        finally:
            conn.close()

        app_logger.info(f"Uninstalled agent pack '{pack_name}' (id={installation_id}): "
                       f"{profiles_deleted} profiles deleted, {profiles_kept} kept, "
                       f"{collections_deleted} collections deleted, {collections_kept} kept")

        return {
            "profiles_deleted": profiles_deleted,
            "collections_deleted": collections_deleted,
            "profiles_kept": profiles_kept,
            "collections_kept": collections_kept,
        }

    # ── List ───────────────────────────────────────────────────────────────────

    async def list_packs(self, user_uuid: str) -> list[dict]:
        """List agent packs for user (owned + subscribed via sharing grants)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT i.id, i.name, i.description, i.version, i.author, "
                "i.coordinator_tag, i.coordinator_profile_id, i.pack_type, i.installed_at, "
                "CASE WHEN i.owner_user_id = ? THEN 1 ELSE 0 END AS is_owned "
                "FROM agent_pack_installations i "
                "LEFT JOIN marketplace_sharing_grants msg "
                "  ON msg.resource_type = 'agent_pack' "
                "  AND msg.resource_id = CAST(i.id AS TEXT) "
                "  AND msg.grantee_user_id = ? "
                "WHERE i.owner_user_id = ? OR msg.id IS NOT NULL "
                "ORDER BY i.installed_at DESC",
                (user_uuid, user_uuid, user_uuid)
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

                profile_count = counts.get("profile", 0)
                pack_type = row["pack_type"] or "genie"

                # For genie packs, experts_count = total profiles - 1 (coordinator)
                # For other packs, experts_count = 0
                if pack_type == "genie" and row["coordinator_tag"]:
                    experts_count = max(profile_count - 1, 0)
                else:
                    experts_count = 0

                packs.append({
                    "installation_id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "version": row["version"],
                    "author": row["author"],
                    "coordinator_tag": row["coordinator_tag"],
                    "coordinator_profile_id": row["coordinator_profile_id"],
                    "pack_type": pack_type,
                    "profiles_count": profile_count,
                    "experts_count": experts_count,
                    "collections_count": counts.get("collection", 0),
                    "installed_at": row["installed_at"],
                    "is_owned": bool(row["is_owned"]),
                })

            return packs
        finally:
            conn.close()

    # ── Details ────────────────────────────────────────────────────────────────

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
                "SELECT resource_type, resource_id, resource_tag, resource_role, is_owned "
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
                "pack_type": row["pack_type"] or "genie",
                "installed_at": row["installed_at"],
                "manifest": json.loads(row["manifest_json"]),
                "resources": resources,
            }
        finally:
            conn.close()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_existing_pack_names(self, user_uuid: str) -> set[str]:
        """Return set of all installed pack names for a user."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM agent_pack_installations WHERE owner_user_id = ?",
                (user_uuid,),
            )
            return {row["name"] for row in cursor.fetchall()}
        finally:
            conn.close()

    def _compute_tag_expansion(
        self,
        conflicting_tags: list[str],
        existing_tags: set[str],
        pack_profiles: list[dict],
    ) -> dict[str, str]:
        """Compute unique tag names for conflicting tags.

        For each conflicting tag, tries TAG2, TAG3, ... until a name is found
        that doesn't collide with existing tags or other pack profile tags.

        Returns: {old_tag: new_tag} only for tags that needed renaming.
        """
        all_pack_tags = {p["tag"] for p in pack_profiles}
        used = existing_tags | all_pack_tags
        remap = {}

        for tag in conflicting_tags:
            counter = 2
            candidate = f"{tag}{counter}"
            while candidate in used:
                counter += 1
                candidate = f"{tag}{counter}"
            remap[tag] = candidate
            used.add(candidate)  # Reserve it for subsequent iterations

        return remap

    def _apply_tag_remap(
        self,
        profiles: list[dict],
        remap: dict[str, str],
    ) -> None:
        """Apply tag remap to all manifest profiles in-place.

        Updates:
        1. prof["tag"] for renamed profiles
        2. child_tags arrays in genie profiles
        """
        if not remap:
            return

        for prof in profiles:
            # Rename the profile's own tag
            if prof["tag"] in remap:
                prof["tag"] = remap[prof["tag"]]

            # Update child_tags references in genie profiles
            if prof.get("child_tags"):
                prof["child_tags"] = [
                    remap.get(ct, ct) for ct in prof["child_tags"]
                ]

    def _build_profile(
        self,
        prof: dict,
        ref_to_collection_id: dict,
        llm_config_id: str,
        mcp_server_id: str | None,
        tag_to_profile_id: dict | None = None,
    ) -> dict:
        """Build a profile data dict from a v1.1 manifest profile entry.

        Handles all 4 profile types: rag_focused, tool_enabled, llm_only, genie.
        """
        profile_id = f"profile-{uuid.uuid4()}"
        profile_type = prof["profile_type"]

        profile_data = {
            "id": profile_id,
            "tag": prof["tag"],
            "name": prof.get("name", prof["tag"]),
            "description": prof.get("description", ""),
            "profile_type": profile_type,
            "llmConfigurationId": llm_config_id,
            "classification_mode": prof.get("classification_mode", "light"),
            "classification_results": {
                "tools": {},
                "prompts": {},
                "resources": {},
                "last_classified": None,
                "classified_with_mode": None,
            },
        }

        collection_refs = prof.get("collection_refs", [])

        if profile_type == "genie":
            # Build genieConfig with resolved child profile IDs
            genie_config = prof.get("genieConfig", {}).copy()
            child_tags = prof.get("child_tags", [])

            if tag_to_profile_id:
                slave_ids = [tag_to_profile_id[ct] for ct in child_tags if ct in tag_to_profile_id]
                genie_config["slaveProfiles"] = slave_ids

            profile_data["genieConfig"] = genie_config

        elif profile_type == "rag_focused":
            if collection_refs:
                knowledge_config = prof.get("knowledgeConfig", {}).copy()
                collections_list = []
                for cr in collection_refs:
                    collection_info = ref_to_collection_id.get(cr)
                    if collection_info:
                        collections_list.append({
                            "id": collection_info["id"],
                            "name": collection_info["name"],
                        })
                if collections_list:
                    knowledge_config["collections"] = collections_list

                synthesis_prompt = prof.get("synthesisPromptOverride")
                if synthesis_prompt:
                    knowledge_config["synthesisPromptOverride"] = synthesis_prompt

                profile_data["knowledgeConfig"] = knowledge_config

        elif profile_type == "tool_enabled":
            if mcp_server_id:
                profile_data["mcpServerId"] = mcp_server_id

            # Link planner collections via ragCollections
            if collection_refs:
                rag_ids = []
                for cr in collection_refs:
                    collection_info = ref_to_collection_id.get(cr)
                    if collection_info:
                        rag_ids.append(collection_info["id"])
                if rag_ids:
                    profile_data["ragCollections"] = rag_ids

        # llm_only needs no extra config

        return profile_data

    def _record_installation(
        self,
        manifest: dict,
        coordinator_tag: str | None,
        coordinator_profile_id: str | None,
        pack_type: str,
        profile_ids: list[str],
        profile_tags: list[str],
        profile_roles: list[str],
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
                 coordinator_profile_id, pack_type, owner_user_id, installed_at, manifest_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                manifest["name"],
                manifest.get("description", ""),
                manifest.get("version", "1.0.0"),
                manifest.get("author", ""),
                coordinator_tag,
                coordinator_profile_id,
                pack_type,
                user_uuid,
                now,
                json.dumps(manifest),
            ))

            installation_id = cursor.lastrowid

            # Record profiles
            for pid, tag, role in zip(profile_ids, profile_tags, profile_roles):
                cursor.execute("""
                    INSERT INTO agent_pack_resources
                    (pack_installation_id, resource_type, resource_id, resource_tag, resource_role)
                    VALUES (?, 'profile', ?, ?, ?)
                """, (installation_id, pid, tag, role))

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
