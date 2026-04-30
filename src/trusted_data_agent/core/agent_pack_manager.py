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


def _build_skill_zip(skill_id: str, manifest: dict, content: str) -> bytes:
    """Build an in-memory .skill zip containing skill.json + markdown + SKILL.md."""
    clean_manifest = {k: v for k, v in manifest.items() if not k.startswith("_")}
    clean_manifest.pop("export_format_version", None)
    clean_manifest.pop("exported_at", None)

    description_safe = clean_manifest.get("description", "").replace("\n", " ")
    skill_md = (
        f"---\nname: {skill_id}\ndescription: {description_safe}\n"
        f"user-invokable: true\n---\n\n{content}"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("skill.json", json.dumps(clean_manifest, indent=2, ensure_ascii=False))
        zf.writestr(f"{skill_id}.md", content)
        zf.writestr("SKILL.md", skill_md)
    return buf.getvalue()


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
        elif version in ("1.1", "1.2", "1.3", "1.4"):
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
        vector_store_config_id: str | None = None,
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

            # Track if we need to restore default profile after replace
            replaced_default_tag = None

            if conflicting_tags:
                if conflict_strategy == "replace":
                    # Delete existing profiles with conflicting tags AND their
                    # orphaned collections (cascade cleanup).
                    from trusted_data_agent.agent.rag_retriever import get_rag_retriever
                    from trusted_data_agent.core.agent_pack_db import AgentPackDB

                    retriever = get_rag_retriever()
                    pack_db = AgentPackDB(self.db_path)

                    # Check if any profile being replaced is the default
                    default_profile_id = config_manager.get_default_profile_id(user_uuid)

                    # Collect all collection IDs referenced by profiles being replaced
                    orphan_collection_ids = set()
                    replaced_profile_ids = []

                    for existing_prof in existing_profiles:
                        if existing_prof.get("tag") not in conflicting_tags:
                            continue

                        replaced_profile_ids.append(existing_prof["id"])

                        # Track if this is the default profile (by tag, for later restoration)
                        if existing_prof["id"] == default_profile_id:
                            replaced_default_tag = existing_prof.get("tag")
                            app_logger.info(
                                f"  Default profile @{replaced_default_tag} will be replaced — "
                                f"will restore default after new profile is created"
                            )

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

                    # Delete orphaned pack installation records whose profiles
                    # were all just replaced (prevents name dedup creating "(2)", "(3)").
                    # Must run BEFORE the orphan collection check so that
                    # is_pack_managed() returns False for collections that were only
                    # held by these now-replaced packs (not by any other pack).
                    old_pack_ids = set()
                    for pid in replaced_profile_ids:
                        for pack_info in pack_db.get_packs_for_resource("profile", str(pid)):
                            old_pack_ids.add(pack_info["id"])
                    for old_id in old_pack_ids:
                        remaining_resources = pack_db.get_resources_for_pack(old_id)
                        profile_resources = [
                            r for r in remaining_resources
                            if r["resource_type"] == "profile"
                        ]
                        # Only delete if all profiles in this pack were replaced
                        all_replaced = all(
                            r["resource_id"] in [str(p) for p in replaced_profile_ids]
                            for r in profile_resources
                        )
                        if all_replaced:
                            pack_db.remove_pack_resources(old_id)
                            conn_tmp = sqlite3.connect(self.db_path)
                            try:
                                conn_tmp.execute(
                                    "DELETE FROM agent_pack_installations WHERE id = ?",
                                    (old_id,),
                                )
                                conn_tmp.commit()
                                app_logger.info(
                                    f"  Deleted old pack installation id={old_id}"
                                )
                            finally:
                                conn_tmp.close()

                    # After profile removal and pack record cleanup, delete collections
                    # that are now truly orphaned (not referenced by any profile or other pack).
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
                            # Check if referenced by a pack other than the ones just replaced
                            if pack_db.is_pack_managed("collection", str(coll_id)):
                                app_logger.info(f"  Kept collection id={coll_id} (still referenced by another pack)")
                                continue
                            if retriever:
                                try:
                                    success = await retriever.remove_collection(coll_id, user_id=user_uuid)
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

            # Step 4b: Import vector store configurations (v1.2+ packs)
            vs_config_map = {}  # ref → local config ID
            import_warnings = []  # governance warnings (non-blocking)

            # Resolve importing user's tier for VS governance checks
            try:
                from trusted_data_agent.vectorstore.settings import get_allowed_backends
                from trusted_data_agent.auth.admin import get_user_tier
                from trusted_data_agent.auth.middleware import get_current_user
                _importing_user = get_current_user()
                _importing_tier = get_user_tier(_importing_user) if _importing_user else "user"
                _allowed_backends = get_allowed_backends(_importing_tier)
            except Exception:
                _allowed_backends = ["chromadb", "teradata", "qdrant"]

            if vector_store_config_id:
                # Override: map ALL pack VS refs to the user-selected config
                # Validate the selected config's backend is allowed for this user's tier
                override_config = next(
                    (c for c in config_manager.get_vector_store_configurations(user_uuid)
                     if c.get("id") == vector_store_config_id), None
                )
                if override_config and override_config.get("backend_type") not in _allowed_backends:
                    raise ValueError(
                        f"Vector store backend '{override_config.get('backend_type')}' "
                        f"is restricted for your tier. Choose a different backend."
                    )
                pack_vs_configs = manifest.get("vector_store_configurations", [])
                for vs_entry in pack_vs_configs:
                    vs_config_map[vs_entry["ref"]] = vector_store_config_id
                app_logger.info(f"Vector store override: all collections → config '{vector_store_config_id}'")
            else:
                # No override: match/create configs from pack manifest (original behavior)
                pack_vs_configs = manifest.get("vector_store_configurations", [])
                if pack_vs_configs:
                    app_logger.info(f"Importing {len(pack_vs_configs)} vector store configurations...")
                    existing_vs_configs = config_manager.get_vector_store_configurations(user_uuid)
                    for vs_entry in pack_vs_configs:
                        match = next((c for c in existing_vs_configs
                                      if c.get("backend_type") == vs_entry.get("backend_type")
                                      and c.get("name") == vs_entry.get("name")), None)
                        if match:
                            vs_config_map[vs_entry["ref"]] = match["id"]
                            app_logger.info(f"  Matched existing vector store config '{match['name']}'")
                        else:
                            import random, string
                            suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                            new_vs_config = {
                                "id": f"vs-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{suffix}",
                                "name": vs_entry.get("name", "Imported Vector Store"),
                                "backend_type": vs_entry.get("backend_type", "chromadb"),
                                "backend_config": vs_entry.get("backend_config", {}),
                                "credentials": {},
                                "created_at": datetime.now(timezone.utc).isoformat()
                            }
                            config_manager.add_vector_store_configuration(new_vs_config, user_uuid)
                            vs_config_map[vs_entry["ref"]] = new_vs_config["id"]
                            app_logger.info(f"  Created vector store config '{new_vs_config['name']}'")

                        # Check governance: block import of restricted backend configs
                        _backend = vs_entry.get("backend_type", "chromadb")
                        if _backend not in _allowed_backends:
                            # Remove from vs_config_map so collections using this ref are skipped
                            vs_config_map.pop(vs_entry["ref"], None)
                            import_warnings.append(
                                f"Vector store backend '{_backend}' (config: {vs_entry.get('name', 'unknown')}) "
                                f"is restricted for your tier. Associated knowledge collections were skipped."
                            )
                            app_logger.warning(
                                f"  VS governance block: backend '{_backend}' restricted for tier '{_importing_tier}', "
                                f"ref '{vs_entry['ref']}' removed from import"
                            )

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

                # Resolve VS config for this collection (override or mapped)
                coll_vs_config_id = None
                if not is_planner:
                    if vector_store_config_id:
                        coll_vs_config_id = vector_store_config_id
                    else:
                        vs_ref = coll_entry.get("vector_store_config_ref")
                        if vs_ref and vs_ref in vs_config_map:
                            coll_vs_config_id = vs_config_map[vs_ref]
                        elif vs_ref and vs_ref not in vs_config_map:
                            # VS ref was removed by governance — skip this knowledge collection
                            import_warnings.append(
                                f"Knowledge collection '{coll_entry.get('name', ref)}' skipped: "
                                f"its vector store backend is restricted for your tier."
                            )
                            app_logger.warning(f"  Skipping collection '{ref}': VS ref '{vs_ref}' blocked by governance")
                            continue

                result = await import_collection_from_zip(
                    zip_path=coll_zip_path,
                    user_uuid=user_uuid,
                    display_name=coll_entry.get("name"),
                    mcp_server_id=coll_mcp,
                    skip_reload=True,
                    populate_knowledge_docs=True,
                    vector_store_config_id=coll_vs_config_id,
                )

                new_coll_id = result["collection_id"]

                # Link collection to imported vector store config (skip if already set via override)
                vs_ref = coll_entry.get("vector_store_config_ref")
                if not coll_vs_config_id and vs_ref and vs_ref in vs_config_map:
                    try:
                        from trusted_data_agent.core.collection_db import get_collection_db
                        coll_db = get_collection_db()
                        coll_db.update_collection(new_coll_id, {"vector_store_config_id": vs_config_map[vs_ref]})
                    except Exception as e:
                        app_logger.warning(f"Could not link collection {new_coll_id} to vector store config: {e}")

                ref_to_collection_id[ref] = {
                    "id": new_coll_id,
                    "name": result["collection_name"],
                }
                app_logger.info(f"  Imported collection '{ref}' -> id={new_coll_id} ({result['document_count']} docs)")

            # Step 5b: Install bundled skills (v1.3+ packs)
            pack_skills = manifest.get("skills", [])
            if pack_skills:
                app_logger.info(f"Installing {len(pack_skills)} skill(s) from agent pack...")
                for skill_ref in pack_skills:
                    skill_id = skill_ref.get("id")
                    skill_file = skill_ref.get("file")
                    if not skill_id or not skill_file:
                        continue
                    skill_zip_path = temp_path / skill_file
                    if not skill_zip_path.exists():
                        app_logger.warning(f"  Skill file not found in pack: {skill_file}")
                        continue
                    try:
                        self._install_skill_from_zip_bytes(skill_id, skill_zip_path.read_bytes())
                    except Exception as e:
                        app_logger.warning(f"  Failed to install skill '{skill_id}': {e}")
                # Reload so profiles can reference the newly installed skills
                try:
                    from trusted_data_agent.skills.manager import get_skill_manager
                    get_skill_manager().reload()
                except Exception as e:
                    app_logger.warning(f"  Failed to reload skill manager after pack import: {e}")

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

            # Step 6b: Restore default profile if it was replaced
            if replaced_default_tag and replaced_default_tag in tag_to_profile_id:
                new_default_id = tag_to_profile_id[replaced_default_tag]
                config_manager.set_default_profile_id(new_default_id, user_uuid)
                app_logger.info(
                    f"  Restored default profile: @{replaced_default_tag} (new id={new_default_id})"
                )

            # Step 6c: Import Knowledge Graphs (needs profile IDs from Step 6)
            pack_kgs = manifest.get("knowledge_graphs", [])
            _kgs_imported = 0
            _imported_kg_ids: list[str] = []
            _imported_kg_names: list[str] = []
            if pack_kgs:
                import uuid as _uuid_kg
                import sqlite3 as _sq_kg
                from components.builtin.knowledge_graph.graph_store import GraphStore as _GS_import
                app_logger.info(f"Importing {len(pack_kgs)} knowledge graph(s)...")

                for _kg_entry in pack_kgs:
                    _kg_profile_tag = _kg_entry.get("profile_tag")
                    _kg_target_profile_id = tag_to_profile_id.get(_kg_profile_tag)
                    if not _kg_target_profile_id:
                        app_logger.warning(
                            f"  KG '{_kg_entry.get('name')}': profile @{_kg_profile_tag} not found, skipping"
                        )
                        continue

                    _kg_file_path = temp_path / _kg_entry["file"]
                    if not _kg_file_path.exists():
                        app_logger.warning(f"  KG file not found in pack: {_kg_entry['file']}")
                        continue

                    _kg_data = json.loads(_kg_file_path.read_text())
                    _new_kg_id = str(_uuid_kg.uuid4())

                    # Determine the KG owner on this system.
                    # Preference order:
                    #   1. owner_profile_tag from manifest (when original owner is in this pack)
                    #   2. Genie coordinator of this pack (neutral owner for cross-pack KGs)
                    #   3. Active-assignment profile (fallback, current behaviour for single profiles)
                    _owner_profile_tag = _kg_entry.get("owner_profile_tag")
                    _actual_owner_pid = tag_to_profile_id.get(_owner_profile_tag) if _owner_profile_tag else None
                    if not _actual_owner_pid:
                        _coord_tag = next(
                            (p["tag"] for p in genie_profiles if p.get("role") == "coordinator"), None
                        )
                        _actual_owner_pid = tag_to_profile_id.get(_coord_tag) if _coord_tag else None
                    if not _actual_owner_pid:
                        _actual_owner_pid = _kg_target_profile_id

                    # Check if the owner already has an active KG — don't displace it
                    _sq_conn = _sq_kg.connect(self.db_path)
                    try:
                        _has_active = _sq_conn.execute(
                            "SELECT 1 FROM kg_metadata WHERE profile_id = ? AND user_uuid = ? AND is_active = 1 LIMIT 1",
                            (_actual_owner_pid, user_uuid),
                        ).fetchone() is not None
                    finally:
                        _sq_conn.close()

                    try:
                        _store = _GS_import(
                            profile_id=_actual_owner_pid,
                            user_uuid=user_uuid,
                            kg_id=_new_kg_id,
                        )
                        _store.set_kg_metadata(
                            name=_kg_data.get("name") or _kg_entry.get("name", "Imported KG"),
                            database_name=_kg_data.get("database_name") or _kg_entry.get("database_name"),
                            description=_kg_data.get("description") or _kg_entry.get("description"),
                            is_active=not _has_active,
                        )
                        _bulk_result = _store.import_bulk(
                            entities=_kg_data.get("entities", []),
                            relationships=_kg_data.get("relationships", []),
                        )
                        app_logger.info(
                            f"  Imported KG '{_kg_entry.get('name')}' -> profile @{_kg_profile_tag} "
                            f"(id={_new_kg_id}, active={not _has_active}, "
                            f"entities={_bulk_result['entities_added']}, "
                            f"rels={_bulk_result['relationships_added']})"
                        )
                        _kgs_imported += 1
                        _imported_kg_ids.append(_new_kg_id)
                        _imported_kg_names.append(_kg_entry.get("name", ""))

                        # Create kg_profile_assignments rows for all assigned pack profiles
                        _assigned_profiles_manifest = _kg_entry.get("assigned_profiles", [])
                        if _assigned_profiles_manifest:
                            _sq_assign = _sq_kg.connect(self.db_path)
                            try:
                                for _ap in _assigned_profiles_manifest:
                                    _ap_tag = _ap.get("tag")
                                    _ap_active_src = bool(_ap.get("is_active", False))
                                    _ap_pid = tag_to_profile_id.get(_ap_tag)
                                    if not _ap_pid:
                                        continue
                                    if _ap_active_src:
                                        _ap_already_active = _sq_assign.execute(
                                            "SELECT 1 FROM kg_profile_assignments "
                                            "WHERE assigned_profile_id=? AND user_uuid=? AND is_active=1 LIMIT 1",
                                            (_ap_pid, user_uuid),
                                        ).fetchone() is not None
                                        _ap_activate = not _ap_already_active
                                    else:
                                        _ap_activate = False
                                    _sq_assign.execute(
                                        "INSERT OR IGNORE INTO kg_profile_assignments "
                                        "(kg_id, kg_owner_profile_id, assigned_profile_id, user_uuid, is_active) "
                                        "VALUES (?, ?, ?, ?, ?)",
                                        (_new_kg_id, _actual_owner_pid, _ap_pid, user_uuid,
                                         1 if _ap_activate else 0),
                                    )
                                _sq_assign.commit()
                            except Exception as _ae:
                                app_logger.warning(
                                    f"  Failed to create KG assignments for '{_kg_entry.get('name')}': {_ae}"
                                )
                            finally:
                                _sq_assign.close()
                    except Exception as _e:
                        app_logger.warning(f"  Failed to import KG '{_kg_entry.get('name')}': {_e}")

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
                kg_ids=_imported_kg_ids,
                kg_names=_imported_kg_names,
                user_uuid=user_uuid,
            )

            result = {
                "installation_id": installation_id,
                "name": manifest["name"],
                "coordinator_tag": coordinator_tag,
                "coordinator_profile_id": coordinator_profile_id,
                "profiles_created": len(created_profile_ids),
                "collections_created": len(ref_to_collection_id),
                "kgs_created": _kgs_imported,
                # Legacy compat
                "experts_created": len(non_genie),
                "tag_remap": tag_remap if tag_remap else None,
                "warnings": import_warnings if import_warnings else None,
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

                        mc_entry = {
                            "ref": safe_ref,
                            "file": f"collections/{final_name}",
                            "name": coll_meta["name"] if coll_meta else coll_info.get("name", ""),
                            "repository_type": coll_meta.get("repository_type", "knowledge") if coll_meta else "knowledge",
                            "description": coll_meta.get("description", "") if coll_meta else "",
                            "backend_type": coll_meta.get("backend_type", "chromadb") if coll_meta else "chromadb",
                            "_source_id": coll_id,  # Internal tracking, stripped before writing
                        }
                        if coll_meta and coll_meta.get("vector_store_config_id"):
                            mc_entry["vector_store_config_ref"] = coll_meta["vector_store_config_id"]
                        manifest_collections.append(mc_entry)

                        collection_refs.append(safe_ref)
                        exported_collection_ids.add(coll_id)

                    except Exception as e:
                        app_logger.warning(f"Failed to export collection {coll_id} for @{profile.get('tag')}: {e}")

                # Also check ragCollections (planner repos for tool-using profiles only)
                profile_type = profile.get("profile_type", "")
                uses_tools = (
                    profile_type == "tool_enabled"
                    or (profile_type == "llm_only" and profile.get("useMcpTools"))
                )
                rag_collection_ids = profile.get("ragCollections", []) if uses_tools else []
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

                        mc_entry = {
                            "ref": safe_ref,
                            "file": f"collections/{final_name}",
                            "name": coll_meta["name"] if coll_meta else "",
                            "repository_type": coll_meta.get("repository_type", "planner") if coll_meta else "planner",
                            "description": coll_meta.get("description", "") if coll_meta else "",
                            "backend_type": coll_meta.get("backend_type", "chromadb") if coll_meta else "chromadb",
                            "_source_id": coll_id,
                        }
                        if coll_meta and coll_meta.get("vector_store_config_id"):
                            mc_entry["vector_store_config_ref"] = coll_meta["vector_store_config_id"]
                        manifest_collections.append(mc_entry)

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
                    "contextWindowTypeId": profile.get("contextWindowTypeId"),
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
                    gc_copy = {k: v for k, v in genie_config.items()
                               if k not in ("slaveProfiles", "slaveProfileSettings")}
                    # Remap slaveProfileSettings keys from profile IDs → profile tags
                    # so they survive export/import without being tied to runtime IDs.
                    slave_settings = genie_config.get("slaveProfileSettings", {})
                    if slave_settings:
                        settings_by_tag = {}
                        for pid, settings in slave_settings.items():
                            child_prof = next((p for p in selected_profiles if p["id"] == pid), None)
                            if child_prof:
                                settings_by_tag[child_prof.get("tag")] = settings
                        if settings_by_tag:
                            gc_copy["slaveProfileSettings"] = settings_by_tag
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

                # Include skillsConfig so auto-enabled skills are preserved
                skills_config = profile.get("skillsConfig")
                if skills_config:
                    prof_entry["skillsConfig"] = skills_config

                manifest_profiles.append(prof_entry)

            # Collect user skills that are auto-enabled (active=True) in any profile's skillsConfig
            skills_to_bundle = {}  # skill_id → {manifest, content}
            try:
                from trusted_data_agent.skills.manager import get_skill_manager
                skill_manager = get_skill_manager()
                for profile in selected_profiles:
                    for skill_entry in profile.get("skillsConfig", {}).get("skills", []):
                        if not skill_entry.get("active", False):
                            continue
                        skill_id = skill_entry.get("id")
                        if not skill_id or skill_id in skills_to_bundle:
                            continue
                        s_manifest = skill_manager.get_skill_manifest(skill_id)
                        if s_manifest and s_manifest.get("_is_user", False):
                            s_content = skill_manager.get_skill_full_content(skill_id)
                            if s_content:
                                skills_to_bundle[skill_id] = {"manifest": s_manifest, "content": s_content}
                                app_logger.info(f"  Will bundle user skill '{skill_id}' (auto-enabled)")
            except Exception as e:
                app_logger.warning(f"Could not collect skills for agent pack export: {e}")

            # Collect active Knowledge Graphs owned by selected profiles
            manifest_kgs = []
            knowledge_graphs_dir = temp_path / "knowledge_graphs"
            kg_counter = 0
            exported_kg_ids: set = set()

            try:
                from components.builtin.knowledge_graph.graph_store import GraphStore as _GS_export
                import sqlite3 as _sqlite3_kg
                all_user_kgs = _GS_export.list_all_graphs(user_uuid)

                try:
                    from trusted_data_agent.core.config import APP_CONFIG
                    _kg_db_path = APP_CONFIG.AUTH_DB_PATH.replace("sqlite:///", "")
                except Exception:
                    _kg_db_path = str(self.db_path)
                _kg_db = _sqlite3_kg.connect(_kg_db_path)
                _kg_db.row_factory = _sqlite3_kg.Row

                for _kg_profile in selected_profiles:
                    _pid = _kg_profile["id"]
                    # Primary: use kg_profile_assignments as source of truth for active KG per profile.
                    # kg_metadata.profile_id is the KG's owner profile which may differ from the
                    # assigned profile (e.g. after profile IDs change).
                    _profile_kgs = []
                    try:
                        _arows = _kg_db.execute(
                            "SELECT kg_id FROM kg_profile_assignments "
                            "WHERE assigned_profile_id = ? AND user_uuid = ? AND is_active = 1",
                            (_pid, user_uuid),
                        ).fetchall()
                        for _arow in _arows:
                            _akg = next(
                                (kg for kg in all_user_kgs
                                 if kg["kg_id"] == _arow[0] and _arow[0] not in exported_kg_ids),
                                None,
                            )
                            if _akg:
                                _profile_kgs.append(_akg)
                    except Exception:
                        pass  # kg_profile_assignments may not exist on very old installs

                    # Fallback: legacy kg_metadata ownership match (KGs created before
                    # kg_profile_assignments existed, or freshly created with no assignment row yet)
                    if not _profile_kgs:
                        _profile_kgs = [
                            kg for kg in all_user_kgs
                            if kg.get("profile_id") == _pid and kg.get("is_active")
                            and kg["kg_id"] not in exported_kg_ids
                        ]
                    _kg_refs_for_profile = []

                    for _kg_meta in _profile_kgs:
                        if _kg_meta["kg_id"] in exported_kg_ids:
                            continue  # safety guard against duplicates

                        kg_counter += 1
                        _kg_ref = f"kg_{kg_counter}"
                        _kg_file_name = f"{_kg_ref}.json"

                        try:
                            _store = _GS_export(
                                profile_id=_pid,
                                user_uuid=user_uuid,
                                kg_id=_kg_meta["kg_id"],
                            )
                            _entities = _store.list_entities(limit=999999)
                            _relationships = _store.list_relationships(limit=999999)
                        except Exception as _e:
                            app_logger.warning(
                                f"Failed to export KG '{_kg_meta.get('kg_name')}': {_e}"
                            )
                            continue

                        if not knowledge_graphs_dir.exists():
                            knowledge_graphs_dir.mkdir()

                        _kg_json = {
                            "name": _kg_meta.get("kg_name", ""),
                            "database_name": _kg_meta.get("database_name", ""),
                            "description": _kg_meta.get("description", ""),
                            "entities": _entities,
                            "relationships": _relationships,
                        }
                        (knowledge_graphs_dir / _kg_file_name).write_text(
                            json.dumps(_kg_json, indent=2, ensure_ascii=False)
                        )

                        _pack_pid_to_tag = {p["id"]: p.get("tag") for p in selected_profiles}
                        _kg_owner_tag = _pack_pid_to_tag.get(_kg_meta.get("profile_id"))

                        _kg_assigned_profiles = []
                        try:
                            _assign_rows = _kg_db.execute(
                                "SELECT assigned_profile_id, is_active FROM kg_profile_assignments "
                                "WHERE kg_id = ? AND user_uuid = ?",
                                (_kg_meta["kg_id"], user_uuid),
                            ).fetchall()
                            for _ar in _assign_rows:
                                _atag = _pack_pid_to_tag.get(_ar["assigned_profile_id"])
                                if _atag:
                                    _kg_assigned_profiles.append(
                                        {"tag": _atag, "is_active": bool(_ar["is_active"])}
                                    )
                        except Exception:
                            pass

                        manifest_kgs.append({
                            "ref": _kg_ref,
                            "file": f"knowledge_graphs/{_kg_file_name}",
                            "profile_tag": _kg_profile.get("tag"),
                            "owner_profile_tag": _kg_owner_tag,
                            "name": _kg_meta.get("kg_name", ""),
                            "database_name": _kg_meta.get("database_name", ""),
                            "description": _kg_meta.get("description", ""),
                            "assigned_profiles": _kg_assigned_profiles,
                        })
                        _kg_refs_for_profile.append(_kg_ref)
                        exported_kg_ids.add(_kg_meta["kg_id"])
                        app_logger.info(
                            f"  Exported KG '{_kg_meta.get('kg_name')}' -> {_kg_file_name}"
                        )

                    # Attach kg_refs to the matching profile entry in manifest_profiles
                    if _kg_refs_for_profile:
                        for _mp in manifest_profiles:
                            if _mp["tag"] == _kg_profile.get("tag"):
                                _mp["kg_refs"] = _kg_refs_for_profile
                                break

                _kg_db.close()
            except Exception as e:
                app_logger.warning(f"Could not collect knowledge graphs for agent pack export: {e}")

            # Gather unique vector store configs referenced by pack collections
            manifest_vs_configs = []
            vs_config_ids = set()
            for mc in manifest_collections:
                vs_ref = mc.get("vector_store_config_ref")
                if vs_ref and vs_ref not in vs_config_ids:
                    vs_config_ids.add(vs_ref)
            if vs_config_ids:
                try:
                    from trusted_data_agent.core.config_manager import get_config_manager
                    config_manager = get_config_manager()
                    vs_configs = config_manager.get_vector_store_configurations(user_uuid)
                    for vs_id in vs_config_ids:
                        vs_config = next((c for c in vs_configs if c.get("id") == vs_id), None)
                        if vs_config:
                            manifest_vs_configs.append({
                                "ref": vs_id,
                                "name": vs_config.get("name", ""),
                                "backend_type": vs_config.get("backend_type", "chromadb"),
                                "backend_config": vs_config.get("backend_config", {}),
                            })
                except Exception as e:
                    app_logger.warning(f"Could not resolve vector store configs for agent pack export: {e}")

            # Strip internal tracking fields from collections
            for mc in manifest_collections:
                mc.pop("_source_id", None)

            # Determine pack name
            if not pack_name:
                genie_prof = next((p for p in selected_profiles if p.get("profile_type") == "genie"), None)
                pack_name = genie_prof.get("name", "Exported Agent Pack") if genie_prof else "Exported Agent Pack"

            # Build skill refs list
            skill_refs = [
                {
                    "id": sid,
                    "file": f"skills/{sid}.skill",
                    "name": data["manifest"].get("name", sid),
                    "description": data["manifest"].get("description", ""),
                }
                for sid, data in skills_to_bundle.items()
            ]

            # Determine manifest version: 1.4 if KGs, 1.3 if skills, 1.2 if VS configs, else 1.1
            if manifest_kgs:
                manifest_version = "1.4"
            elif skill_refs:
                manifest_version = "1.3"
            elif manifest_vs_configs:
                manifest_version = "1.2"
            else:
                manifest_version = "1.1"

            manifest = {
                "format_version": manifest_version,
                "name": pack_name,
                "description": pack_description or "",
                "author": "",
                "version": "1.0.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "tags": [],
                "profiles": manifest_profiles,
                "collections": manifest_collections,
            }
            if manifest_vs_configs:
                manifest["vector_store_configurations"] = manifest_vs_configs
            if skill_refs:
                manifest["skills"] = skill_refs
            if manifest_kgs:
                manifest["knowledge_graphs"] = manifest_kgs

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
                for skill_id, skill_data in skills_to_bundle.items():
                    skill_zip_bytes = _build_skill_zip(skill_id, skill_data["manifest"], skill_data["content"])
                    zf.writestr(f"skills/{skill_id}.skill", skill_zip_bytes)
                if knowledge_graphs_dir.exists():
                    for _kg_file in knowledge_graphs_dir.rglob("*.json"):
                        zf.write(_kg_file, f"knowledge_graphs/{_kg_file.name}")

            app_logger.info(f"Exported agent pack to {agentpack_path} ({agentpack_path.stat().st_size / 1024 / 1024:.2f} MB)")
            return agentpack_path

        except (ValueError, RuntimeError):
            raise
        except Exception as e:
            app_logger.error(f"Failed to export agent pack: {e}", exc_info=True)
            raise RuntimeError(f"Failed to export agent pack: {e}")

    # ── Create & Install (local) ─────────────────────────────────────────────

    async def create_and_install(
        self,
        profile_ids: list[str],
        user_uuid: str,
        pack_name: str = "",
        pack_description: str = "",
    ) -> dict:
        """Create an agent pack from existing profiles and register it locally.

        Unlike the export→import flow, this references existing profiles and
        collections with is_owned=0 so that uninstalling the pack does NOT
        delete the original resources.

        Returns: dict with installation details.
        """
        from trusted_data_agent.core.config_manager import get_config_manager

        config_manager = get_config_manager()

        # Export the .agentpack ZIP (for potential sharing/download later)
        zip_path = await self.export_pack(
            profile_ids=profile_ids,
            user_uuid=user_uuid,
            pack_name=pack_name,
            pack_description=pack_description,
        )

        # Read back the manifest to get profile metadata
        import zipfile as zf_mod
        with zf_mod.ZipFile(zip_path, 'r') as zf:
            manifest = json.loads(zf.read("manifest.json"))

        # Resolve actual profile objects
        selected_profiles = []
        selected_ids = set(profile_ids)
        for pid in profile_ids:
            profile = config_manager.get_profile(pid, user_uuid)
            if profile:
                selected_profiles.append(profile)

        # Auto-include genie children
        for profile in list(selected_profiles):
            if profile.get("profile_type") == "genie":
                child_ids = profile.get("genieConfig", {}).get("slaveProfiles", [])
                for child_id in child_ids:
                    if child_id not in selected_ids:
                        child = config_manager.get_profile(child_id, user_uuid)
                        if child:
                            selected_profiles.append(child)
                            selected_ids.add(child_id)

        # Build lists for _record_installation
        rec_profile_ids = []
        rec_profile_tags = []
        rec_profile_roles = []

        genie_child_ids = set()
        for profile in selected_profiles:
            if profile.get("profile_type") == "genie":
                genie_child_ids.update(profile.get("genieConfig", {}).get("slaveProfiles", []))

        coordinator_tag = None
        coordinator_profile_id = None

        for profile in selected_profiles:
            rec_profile_ids.append(profile["id"])
            rec_profile_tags.append(profile.get("tag", ""))

            if profile.get("profile_type") == "genie":
                role = "coordinator"
                coordinator_tag = profile.get("tag")
                coordinator_profile_id = profile["id"]
            elif profile["id"] in genie_child_ids:
                role = "expert"
            else:
                role = "standalone"
            rec_profile_roles.append(role)

        # Gather existing collection IDs from profiles
        rec_collection_ids = []
        rec_collection_refs = []
        seen_collection_ids = set()

        for i, profile in enumerate(selected_profiles):
            # Knowledge collections
            for kc in profile.get("knowledgeConfig", {}).get("collections", []):
                cid = kc.get("id")
                if cid and cid not in seen_collection_ids:
                    seen_collection_ids.add(cid)
                    rec_collection_ids.append(int(cid))
                    rec_collection_refs.append(kc.get("name", f"collection_{cid}"))

            # Planner collections (tool_enabled only)
            if profile.get("profile_type") == "tool_enabled" or (
                profile.get("profile_type") == "llm_only" and profile.get("useMcpTools")
            ):
                for cid in profile.get("ragCollections", []):
                    if cid and cid != '*' and cid not in seen_collection_ids:
                        seen_collection_ids.add(cid)
                        rec_collection_ids.append(int(cid))
                        rec_collection_refs.append(f"planner_{cid}")

        # Determine pack type
        has_genie = any(p.get("profile_type") == "genie" for p in selected_profiles)
        pack_type = "genie" if has_genie else "standalone"

        # Record installation with is_owned=False (references existing resources)
        installation_id = self._record_installation(
            manifest=manifest,
            coordinator_tag=coordinator_tag,
            coordinator_profile_id=coordinator_profile_id,
            pack_type=pack_type,
            profile_ids=rec_profile_ids,
            profile_tags=rec_profile_tags,
            profile_roles=rec_profile_roles,
            collection_ids=rec_collection_ids,
            collection_refs=rec_collection_refs,
            user_uuid=user_uuid,
            is_owned=False,
        )

        # Store the ZIP path in manifest for potential download
        app_logger.info(
            f"Created and installed agent pack '{pack_name}' "
            f"(installation_id={installation_id}, "
            f"{len(rec_profile_ids)} profiles, "
            f"{len(rec_collection_ids)} collections, is_owned=False)"
        )

        return {
            "status": "success",
            "installation_id": installation_id,
            "name": manifest["name"],
            "profiles_created": len(rec_profile_ids),
            "collections_created": len(rec_collection_ids),
            "zip_path": str(zip_path),
        }

    # ── Update Pack Profiles ───────────────────────────────────────────────────

    async def update_pack_profiles(
        self,
        installation_id: int,
        user_uuid: str,
        profile_ids: list[str],
    ) -> dict:
        """Replace the profiles referenced by an installed agent pack.

        Resolves coordinator/expert roles automatically (same logic as
        create_and_install). All resources are marked is_owned=0 since
        we reference existing profiles, not own them.

        Returns: dict with updated coordinator_tag, pack_type, profile counts.
        """
        from trusted_data_agent.core.config_manager import get_config_manager

        config_manager = get_config_manager()

        # Validate ownership
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM agent_pack_installations WHERE id = ? AND owner_user_id = ?",
                (installation_id, user_uuid),
            )
            if not cursor.fetchone():
                raise ValueError(f"Pack {installation_id} not found or access denied")
        finally:
            conn.close()

        # Resolve profiles + auto-include genie children
        selected_profiles = []
        selected_ids = set(profile_ids)
        for pid in profile_ids:
            profile = config_manager.get_profile(pid, user_uuid)
            if profile:
                selected_profiles.append(profile)

        for profile in list(selected_profiles):
            if profile.get("profile_type") == "genie":
                for child_id in profile.get("genieConfig", {}).get("slaveProfiles", []):
                    if child_id not in selected_ids:
                        child = config_manager.get_profile(child_id, user_uuid)
                        if child:
                            selected_profiles.append(child)
                            selected_ids.add(child_id)

        # Compute coordinator/expert roles
        genie_child_ids: set[str] = set()
        for profile in selected_profiles:
            if profile.get("profile_type") == "genie":
                genie_child_ids.update(profile.get("genieConfig", {}).get("slaveProfiles", []))

        rec_profile_ids: list[str] = []
        rec_profile_tags: list[str] = []
        rec_profile_roles: list[str] = []
        coordinator_tag = None
        coordinator_profile_id = None

        for profile in selected_profiles:
            rec_profile_ids.append(profile["id"])
            rec_profile_tags.append(profile.get("tag", ""))
            if profile.get("profile_type") == "genie":
                role = "coordinator"
                coordinator_tag = profile.get("tag")
                coordinator_profile_id = profile["id"]
            elif profile["id"] in genie_child_ids:
                role = "expert"
            else:
                role = "standalone"
            rec_profile_roles.append(role)

        # Gather collections from selected profiles
        rec_collection_ids: list[int] = []
        rec_collection_refs: list[str] = []
        seen_collection_ids: set = set()

        for profile in selected_profiles:
            for kc in profile.get("knowledgeConfig", {}).get("collections", []):
                cid = kc.get("id")
                if cid and cid not in seen_collection_ids:
                    seen_collection_ids.add(cid)
                    rec_collection_ids.append(int(cid))
                    rec_collection_refs.append(kc.get("name", f"collection_{cid}"))
            if profile.get("profile_type") == "tool_enabled" or (
                profile.get("profile_type") == "llm_only" and profile.get("useMcpTools")
            ):
                for cid in profile.get("ragCollections", []):
                    if cid and cid != "*" and cid not in seen_collection_ids:
                        seen_collection_ids.add(cid)
                        rec_collection_ids.append(int(cid))
                        rec_collection_refs.append(f"planner_{cid}")

        has_genie = any(p.get("profile_type") == "genie" for p in selected_profiles)
        pack_type = "genie" if has_genie else "standalone"

        # Persist changes
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Update header fields
            cursor.execute(
                """UPDATE agent_pack_installations
                   SET coordinator_tag = ?, coordinator_profile_id = ?, pack_type = ?
                   WHERE id = ?""",
                (coordinator_tag, coordinator_profile_id, pack_type, installation_id),
            )

            # Replace all resource rows
            cursor.execute(
                "DELETE FROM agent_pack_resources WHERE pack_installation_id = ?",
                (installation_id,),
            )

            for pid, tag, role in zip(rec_profile_ids, rec_profile_tags, rec_profile_roles):
                cursor.execute(
                    """INSERT INTO agent_pack_resources
                       (pack_installation_id, resource_type, resource_id, resource_tag, resource_role, is_owned)
                       VALUES (?, 'profile', ?, ?, ?, 0)""",
                    (installation_id, pid, tag, role),
                )

            for coll_id, ref in zip(rec_collection_ids, rec_collection_refs):
                cursor.execute(
                    """INSERT INTO agent_pack_resources
                       (pack_installation_id, resource_type, resource_id, resource_tag, resource_role, is_owned)
                       VALUES (?, 'collection', ?, ?, 'collection', 0)""",
                    (installation_id, str(coll_id), ref),
                )

            conn.commit()
        finally:
            conn.close()

        app_logger.info(
            f"Updated pack {installation_id} profiles: {len(rec_profile_ids)} profiles, "
            f"{len(rec_collection_ids)} collections, coordinator=@{coordinator_tag}"
        )

        return {
            "coordinator_tag": coordinator_tag,
            "pack_type": pack_type,
            "profiles_count": len(rec_profile_ids),
            "collections_count": len(rec_collection_ids),
        }

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

        # Check if any profile being deleted is the default profile
        profile_resources = [r for r in resources if r["resource_type"] == "profile"]
        default_profile_id = config_manager.get_default_profile_id(user_uuid)

        for res in profile_resources:
            if res["resource_id"] == default_profile_id:
                # Check if still referenced by another pack
                if not pack_db.is_pack_managed(res["resource_type"], res["resource_id"]):
                    raise ValueError(
                        f"Cannot uninstall agent pack: profile '@{res['resource_tag']}' is set as "
                        f"the default profile. Please change the default profile first, then "
                        f"try uninstalling again."
                    )

        # Master classification constraint: block if any pack profile is a master for profiles
        # outside this pack (dependents not being deleted in this same operation)
        pack_profile_ids = {r["resource_id"] for r in profile_resources}
        for res in profile_resources:
            if pack_db.is_pack_managed(res["resource_type"], res["resource_id"]):
                continue  # still referenced by another pack, won't be deleted
            dependent_profiles = config_manager.get_dependent_profiles(res["resource_id"], user_uuid)
            external_dependents = [p for p in dependent_profiles if p["id"] not in pack_profile_ids]
            if external_dependents:
                dep_names = ", ".join(
                    f"@{p.get('tag', '?')} ({p.get('name', p.get('id'))})"
                    for p in external_dependents
                )
                raise ValueError(
                    f"Cannot uninstall agent pack '{pack_name}': profile "
                    f"'@{res['resource_tag']}' is the master classification profile for: "
                    f"{dep_names}. Remove the 'Inherit Classification' setting from those "
                    f"profiles first."
                )

        # Step 1: Remove junction rows for THIS pack
        pack_db.remove_pack_resources(installation_id)

        # Step 2: Delete resources that are no longer referenced by ANY pack
        profiles_deleted = 0
        collections_deleted = 0
        profiles_kept = 0
        collections_kept = 0
        total_sessions_archived = 0

        # Separate profiles, collections, and knowledge graphs; process profiles first
        profile_resources = [r for r in resources if r["resource_type"] == "profile"]
        collection_resources = [r for r in resources if r["resource_type"] == "collection"]
        kg_resources = [r for r in resources if r["resource_type"] == "knowledge_graph"]

        # Sort profiles: coordinator first, then others
        coordinators = [r for r in profile_resources if r["resource_role"] == "coordinator"]
        others = [r for r in profile_resources if r["resource_role"] != "coordinator"]

        for res in coordinators + others:
            still_referenced = pack_db.is_pack_managed(res["resource_type"], res["resource_id"])

            if not still_referenced and res.get("is_owned", 1):
                try:
                    # Archive sessions that use this profile before deleting it
                    from trusted_data_agent.core.session_manager import archive_sessions_by_profile
                    archive_result = await archive_sessions_by_profile(res["resource_id"], user_uuid)
                    if archive_result["archived_count"] > 0:
                        total_sessions_archived += archive_result["archived_count"]
                        app_logger.info(
                            f"  Archived {archive_result['archived_count']} sessions for profile "
                            f"@{res['resource_tag']} (including {archive_result['genie_children_archived']} Genie children)"
                        )

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

                    # Archive sessions that use this collection before deleting it
                    from trusted_data_agent.core.session_manager import archive_sessions_by_collection
                    archive_result = await archive_sessions_by_collection(str(collection_id), user_uuid)
                    if archive_result["archived_count"] > 0:
                        total_sessions_archived += archive_result["archived_count"]
                        app_logger.info(
                            f"  Archived {archive_result['archived_count']} sessions for collection id={collection_id}"
                        )

                    if retriever:
                        success = await retriever.remove_collection(collection_id, user_id=user_uuid)
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

        # Delete knowledge graphs
        kgs_deleted = 0
        for res in kg_resources:
            kg_id = res["resource_id"]
            try:
                conn_kg = sqlite3.connect(self.db_path)
                try:
                    conn_kg.execute("DELETE FROM kg_relationships WHERE kg_id = ?", (kg_id,))
                    conn_kg.execute("DELETE FROM kg_entities WHERE kg_id = ?", (kg_id,))
                    conn_kg.execute("DELETE FROM kg_metadata WHERE kg_id = ?", (kg_id,))
                    conn_kg.execute("DELETE FROM kg_profile_assignments WHERE kg_id = ?", (kg_id,))
                    conn_kg.commit()
                finally:
                    conn_kg.close()
                kgs_deleted += 1
                app_logger.info(f"  Deleted KG id={kg_id} ('{res['resource_tag']}')")
            except Exception as e:
                app_logger.warning(f"  Failed to delete KG id={kg_id}: {e}")

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
                       f"{collections_deleted} collections deleted, {collections_kept} kept, "
                       f"{kgs_deleted} KGs deleted, "
                       f"{total_sessions_archived} sessions archived")

        return {
            "profiles_deleted": profiles_deleted,
            "collections_deleted": collections_deleted,
            "kgs_deleted": kgs_deleted,
            "profiles_kept": profiles_kept,
            "collections_kept": collections_kept,
            "sessions_archived": total_sessions_archived,
        }

    # ── List ───────────────────────────────────────────────────────────────────

    async def list_packs(self, user_uuid: str) -> list[dict]:
        """List agent packs for user (owned + subscribed via sharing grants)."""
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()

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

                # For genie packs, derive experts_count from LIVE coordinator profile
                # (the resources table is a snapshot from install time and becomes stale)
                if pack_type == "genie" and row["coordinator_profile_id"]:
                    coord_prof = config_manager.get_profile(row["coordinator_profile_id"], user_uuid)
                    if coord_prof:
                        experts_count = len(coord_prof.get("genieConfig", {}).get("slaveProfiles", []))
                    else:
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

    def _install_skill_from_zip_bytes(self, skill_id: str, zip_bytes: bytes) -> None:
        """Install a skill from in-memory zip bytes into the user skills directory."""
        from trusted_data_agent.skills.manager import get_skill_manager
        buf = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
            manifest_data = {}
            if "skill.json" in names:
                manifest_data = json.loads(zf.read("skill.json").decode("utf-8"))

            # Prefer <skill_id>.md, fall back to any .md, then SKILL.md
            md_file = f"{skill_id}.md"
            if md_file not in names:
                candidates = [n for n in names if n.endswith(".md") and n != "SKILL.md"]
                md_file = candidates[0] if candidates else ("SKILL.md" if "SKILL.md" in names else None)

            if md_file is None:
                app_logger.warning(f"  No markdown content found in skill zip for '{skill_id}', skipping")
                return

            raw = zf.read(md_file).decode("utf-8")

            # Strip YAML frontmatter if reading from SKILL.md
            if md_file == "SKILL.md" and raw.startswith("---"):
                end = raw.find("---", 3)
                raw = raw[end + 3:].lstrip("\n") if end > 0 else raw

            manifest_data.pop("export_format_version", None)
            manifest_data.pop("exported_at", None)

        skill_manager = get_skill_manager()
        skill_manager.save_skill(skill_id, raw, manifest_data)
        app_logger.info(f"  Installed skill '{skill_id}' from agent pack")

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
            "contextWindowTypeId": prof.get("contextWindowTypeId") or "cwt-default-balanced",
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

                # Remap slaveProfileSettings keys from profile tags → new profile IDs
                settings_by_tag = genie_config.get("slaveProfileSettings", {})
                if settings_by_tag:
                    genie_config["slaveProfileSettings"] = {
                        tag_to_profile_id[tag]: settings
                        for tag, settings in settings_by_tag.items()
                        if tag in tag_to_profile_id
                    }

            profile_data["genieConfig"] = genie_config

        elif profile_type == "rag_focused":
            # Always get knowledgeConfig from manifest (preserves settings like maxDocs, maxTokens)
            knowledge_config = prof.get("knowledgeConfig", {}).copy()

            # Add collections if collection_refs exist
            if collection_refs:
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

            # Add synthesis prompt override if exists
            synthesis_prompt = prof.get("synthesisPromptOverride")
            if synthesis_prompt:
                knowledge_config["synthesisPromptOverride"] = synthesis_prompt

            # Always set knowledgeConfig (even if no collection_refs)
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

        elif profile_type == "llm_only":
            # llm_only profiles can optionally use MCP tools via LangChain
            if prof.get("useMcpTools"):
                profile_data["useMcpTools"] = True
                if mcp_server_id:
                    profile_data["mcpServerId"] = mcp_server_id
            elif mcp_server_id and prof.get("mcpServerName"):
                profile_data["mcpServerId"] = mcp_server_id

        # Pre-qualify tool set — non-empty list prevents auto-init to all MCP tools
        # Applies to both tool_enabled and llm_only (useMcpTools) profiles
        allowed_tools = prof.get("allowed_tools")
        if allowed_tools:
            profile_data["tools"] = allowed_tools

        # Restore skillsConfig (auto-enabled skill assignments)
        skills_config = prof.get("skillsConfig")
        if skills_config:
            profile_data["skillsConfig"] = skills_config

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
        is_owned: bool = True,
        kg_ids: list[str] | None = None,
        kg_names: list[str] | None = None,
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
            owned_int = 1 if is_owned else 0
            for pid, tag, role in zip(profile_ids, profile_tags, profile_roles):
                cursor.execute("""
                    INSERT INTO agent_pack_resources
                    (pack_installation_id, resource_type, resource_id, resource_tag, resource_role, is_owned)
                    VALUES (?, 'profile', ?, ?, ?, ?)
                """, (installation_id, pid, tag, role, owned_int))

            # Record collections
            for coll_id, ref in zip(collection_ids, collection_refs):
                cursor.execute("""
                    INSERT INTO agent_pack_resources
                    (pack_installation_id, resource_type, resource_id, resource_tag, resource_role, is_owned)
                    VALUES (?, 'collection', ?, ?, 'collection', ?)
                """, (installation_id, str(coll_id), ref, owned_int))

            # Record knowledge graphs
            for kg_id, kg_name in zip(kg_ids or [], kg_names or []):
                cursor.execute("""
                    INSERT INTO agent_pack_resources
                    (pack_installation_id, resource_type, resource_id, resource_tag, resource_role, is_owned)
                    VALUES (?, 'knowledge_graph', ?, ?, 'knowledge_graph', ?)
                """, (installation_id, kg_id, kg_name, owned_int))

            conn.commit()
            return installation_id
        finally:
            conn.close()
