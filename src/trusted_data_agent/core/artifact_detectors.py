"""
Artifact relationship detection logic.

Each detector implements artifact-specific logic for finding
sessions, profiles, and other artifacts that reference it.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any
import json
import logging

logger = logging.getLogger("quart.app")


class BaseDetector(ABC):
    """Base class for artifact relationship detection."""

    @abstractmethod
    async def find_sessions(
        self,
        artifact_id: str,
        user_uuid: str,
        include_archived: bool = False
    ) -> Dict[str, Any]:
        """
        Find sessions that reference this artifact.

        IMPORTANT: Must distinguish between active and archived sessions.
        Session archived status is determined by checking:
        - session_data.get("is_archived") == True, OR
        - session_data.get("archived") == True

        Returns:
            Dict: {
                "active": [
                    {
                        "session_id": str,
                        "session_name": str,
                        "relationship_type": str,
                        "details": str,
                        "is_archived": False
                    }
                ],
                "archived": [
                    {
                        "session_id": str,
                        "session_name": str,
                        "relationship_type": str,
                        "details": str,
                        "is_archived": True
                    }
                ]
            }
        """
        pass

    @abstractmethod
    async def find_profiles(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """
        Find profiles that reference this artifact.

        Returns:
            List[Dict]: [
                {
                    "profile_id": str,
                    "profile_name": str,
                    "profile_tag": str,
                    "relationship_type": str
                }
            ]
        """
        pass

    @abstractmethod
    async def find_agent_packs(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """
        Find agent packs that manage this artifact.

        Returns:
            List[Dict]: [
                {
                    "pack_id": int,
                    "pack_name": str,
                    "relationship_type": str  # "manages", "depends_on"
                }
            ]
        """
        pass


class CollectionDetector(BaseDetector):
    """Detects relationships for RAG collections (planner/knowledge repositories)."""

    async def find_sessions(
        self,
        artifact_id: str,
        user_uuid: str,
        include_archived: bool = False
    ) -> Dict[str, Any]:
        """
        Find sessions using this collection.

        Detection methods:
        1. Direct: session.rag_collection_id == artifact_id (rag_focused profiles)
        2. Workflow: session.workflow_history[].collection_id == artifact_id (tool_enabled profiles)
        3. Profile: session.profile has collection in knowledgeConfig.collections

        Returns separate lists for active and archived sessions.
        """
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.core.session_manager import SESSIONS_DIR
        import aiofiles

        active_sessions = []
        archived_sessions = []
        collection_id = int(artifact_id)
        collection_str = str(artifact_id)

        user_session_dir = Path(SESSIONS_DIR) / user_uuid
        if not user_session_dir.exists():
            return {"active": [], "archived": []}

        config_manager = get_config_manager()
        user_profiles = config_manager.get_profiles(user_uuid)

        for session_file in user_session_dir.glob("*.json"):
            try:
                async with aiofiles.open(session_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    session_data = json.loads(content)

                session_id = session_data.get("id")
                session_name = session_data.get("name", "Unnamed Session")

                # Check if session is archived (two possible field names)
                is_session_archived = session_data.get("is_archived") or session_data.get("archived")

                # Skip archived sessions if not requested
                if is_session_archived and not include_archived:
                    continue

                session_added = False

                # Method 1: Direct rag_collection_id reference
                rag_coll_id = session_data.get("rag_collection_id")
                if rag_coll_id and (str(rag_coll_id) == collection_str or rag_coll_id == collection_id):
                    session_info = {
                        "session_id": session_id,
                        "session_name": session_name,
                        "relationship_type": "direct_reference",
                        "details": "Session directly uses this collection (rag_focused profile)",
                        "is_archived": bool(is_session_archived)
                    }

                    if is_session_archived:
                        archived_sessions.append(session_info)
                    else:
                        active_sessions.append(session_info)
                    session_added = True
                    continue

                # Method 2: Workflow history references
                if not session_added:
                    workflow = session_data.get("last_turn_data", {}).get("workflow_history", [])
                    for turn in workflow:
                        rag_coll_id = turn.get("rag_source_collection_id")
                        if rag_coll_id and (str(rag_coll_id) == collection_str or rag_coll_id == collection_id):
                            session_info = {
                                "session_id": session_id,
                                "session_name": session_name,
                                "relationship_type": "workflow_history",
                                "details": "Queried this collection in conversation history",
                                "is_archived": bool(is_session_archived)
                            }

                            if is_session_archived:
                                archived_sessions.append(session_info)
                            else:
                                active_sessions.append(session_info)
                            session_added = True
                            break

                        knowledge_sources = turn.get("knowledge_sources", [])
                        for source in knowledge_sources:
                            coll_id = source.get("collection_id")
                            if coll_id and (str(coll_id) == collection_str or coll_id == collection_id):
                                session_info = {
                                    "session_id": session_id,
                                    "session_name": session_name,
                                    "relationship_type": "workflow_history",
                                    "details": "Used this collection as knowledge source",
                                    "is_archived": bool(is_session_archived)
                                }

                                if is_session_archived:
                                    archived_sessions.append(session_info)
                                else:
                                    active_sessions.append(session_info)
                                session_added = True
                                break

                        if session_added:
                            break

                # Method 3: Profile configuration
                if not session_added:
                    session_profile_id = session_data.get("profile_id")
                    profile_tags_used = session_data.get("profile_tags_used", [])

                    # Check current profile
                    profile_ids_to_check = set()
                    if session_profile_id:
                        profile_ids_to_check.add(session_profile_id)

                    # Map historical tags to profile IDs
                    for tag in profile_tags_used:
                        for profile in user_profiles:
                            if profile.get("tag") == tag:
                                profile_ids_to_check.add(profile.get("id"))
                                break

                    # Check if any of these profiles have the collection configured
                    for pid in profile_ids_to_check:
                        profile = next((p for p in user_profiles if p.get("id") == pid), None)
                        if profile:
                            knowledge_config = profile.get("knowledgeConfig", {})
                            if knowledge_config.get("enabled"):
                                profile_collections = knowledge_config.get("collections", [])
                                for coll_info in profile_collections:
                                    coll_id = coll_info.get("id")
                                    if coll_id == collection_id or str(coll_id) == collection_str:
                                        profile_name = profile.get("name", "Unknown Profile")
                                        profile_tag = profile.get("tag", "")
                                        session_info = {
                                            "session_id": session_id,
                                            "session_name": session_name,
                                            "relationship_type": "profile_configuration",
                                            "details": f"Uses profile @{profile_tag} ({profile_name}) which has this collection configured",
                                            "is_archived": bool(is_session_archived)
                                        }

                                        if is_session_archived:
                                            archived_sessions.append(session_info)
                                        else:
                                            active_sessions.append(session_info)
                                        session_added = True
                                        break

                            if session_added:
                                break

            except Exception as e:
                logger.warning(f"Error checking session {session_file}: {e}")
                continue

        # Deduplicate by session_id (separately for active and archived)
        def deduplicate(sessions_list):
            seen_ids = set()
            unique = []
            for sess in sessions_list:
                if sess["session_id"] not in seen_ids:
                    seen_ids.add(sess["session_id"])
                    unique.append(sess)
            return unique

        active_sessions = deduplicate(active_sessions)
        archived_sessions = deduplicate(archived_sessions)

        return {
            "active": active_sessions,
            "archived": archived_sessions
        }

    async def find_profiles(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """Find profiles that have this collection in knowledgeConfig."""
        from trusted_data_agent.core.config_manager import get_config_manager

        config_manager = get_config_manager()
        user_profiles = config_manager.get_profiles(user_uuid)

        profiles_found = []
        collection_id = int(artifact_id)
        collection_str = str(artifact_id)

        for profile in user_profiles:
            knowledge_config = profile.get("knowledgeConfig", {})
            if knowledge_config.get("enabled"):
                profile_collections = knowledge_config.get("collections", [])
                for coll_info in profile_collections:
                    # Handle both int (collection ID) and dict (collection info)
                    if isinstance(coll_info, dict):
                        coll_id = coll_info.get("id")
                    else:
                        # coll_info is the collection ID itself
                        coll_id = coll_info

                    if coll_id and (coll_id == collection_id or str(coll_id) == collection_str):
                        profiles_found.append({
                            "profile_id": profile.get("id"),
                            "profile_name": profile.get("name", "Unknown Profile"),
                            "profile_tag": profile.get("tag", ""),
                            "relationship_type": "knowledge_configuration"
                        })
                        break

        return profiles_found

    async def find_agent_packs(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """Find agent packs that manage this collection."""
        try:
            from trusted_data_agent.core.agent_pack_db import AgentPackDB

            pack_db = AgentPackDB()
            packs = pack_db.get_packs_for_resource("collection", str(artifact_id))

            return [
                {
                    "pack_id": pack["installation_id"],
                    "pack_name": pack["name"],
                    "relationship_type": "manages"
                }
                for pack in packs
            ]
        except Exception as e:
            logger.warning(f"Error finding agent packs for collection {artifact_id}: {e}")
            return []


class ProfileDetector(BaseDetector):
    """Detects relationships for execution profiles."""

    async def find_sessions(
        self,
        artifact_id: str,
        user_uuid: str,
        include_archived: bool = False
    ) -> Dict[str, Any]:
        """
        Find sessions using this profile.

        Detection methods:
        1. Direct: session.profile_id == artifact_id (current profile)
        2. Historical: artifact_id in session.profile_tags_used (historical usage)
        """
        from trusted_data_agent.core.session_manager import SESSIONS_DIR
        from trusted_data_agent.core.config_manager import get_config_manager
        import aiofiles

        active_sessions = []
        archived_sessions = []
        # Normalize to string for consistent comparisons
        profile_id_str = str(artifact_id)

        user_session_dir = Path(SESSIONS_DIR) / user_uuid
        if not user_session_dir.exists():
            return {"active": [], "archived": []}

        # Get profile tag for historical matching
        config_manager = get_config_manager()
        user_profiles = config_manager.get_profiles(user_uuid)
        target_profile = next((p for p in user_profiles if str(p.get("id")) == profile_id_str), None)
        target_tag = target_profile.get("tag") if target_profile else None

        for session_file in user_session_dir.glob("*.json"):
            try:
                async with aiofiles.open(session_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    session_data = json.loads(content)

                session_id = session_data.get("id")
                session_name = session_data.get("name", "Unnamed Session")
                session_profile_id = session_data.get("profile_id")
                profile_tags_used = session_data.get("profile_tags_used", [])

                # Check if session is archived
                is_session_archived = session_data.get("is_archived") or session_data.get("archived")

                # Skip archived sessions if not requested
                if is_session_archived and not include_archived:
                    continue

                session_added = False

                # Check if this is a Genie child session
                genie_meta = session_data.get("genie_metadata", {})
                slave_id = genie_meta.get("slave_profile_id")
                is_genie_child = slave_id and str(slave_id) == profile_id_str

                # Check current profile
                if session_profile_id and str(session_profile_id) == profile_id_str:
                    session_info = {
                        "session_id": session_id,
                        "session_name": session_name,
                        "relationship_type": "current_profile",
                        "details": "Currently using this profile",
                        "is_archived": bool(is_session_archived),
                        "is_genie_child": is_genie_child
                    }

                    if is_session_archived:
                        archived_sessions.append(session_info)
                    else:
                        active_sessions.append(session_info)
                    session_added = True

                # Check historical usage (if not already added)
                if not session_added and target_tag and target_tag in profile_tags_used:
                    session_info = {
                        "session_id": session_id,
                        "session_name": session_name,
                        "relationship_type": "historical_profile",
                        "details": f"Used this profile (@{target_tag}) in conversation history",
                        "is_archived": bool(is_session_archived),
                        "is_genie_child": is_genie_child
                    }

                    if is_session_archived:
                        archived_sessions.append(session_info)
                    else:
                        active_sessions.append(session_info)
                    session_added = True

                # Check Genie child (if not already added by other checks)
                if not session_added and is_genie_child:
                    session_info = {
                        "session_id": session_id,
                        "session_name": session_name,
                        "relationship_type": "genie_child",
                        "details": "Genie child session using this profile",
                        "is_archived": bool(is_session_archived),
                        "is_genie_child": True
                    }

                    if is_session_archived:
                        archived_sessions.append(session_info)
                    else:
                        active_sessions.append(session_info)

            except Exception as e:
                logger.warning(f"Error checking session {session_file}: {e}")
                continue

        return {
            "active": active_sessions,
            "archived": archived_sessions
        }

    async def find_profiles(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """Profiles don't reference other profiles (return empty)."""
        return []

    async def find_agent_packs(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """Find agent packs that manage this profile."""
        try:
            from trusted_data_agent.core.agent_pack_db import AgentPackDB

            pack_db = AgentPackDB()
            packs = pack_db.get_packs_for_resource("profile", artifact_id)

            return [
                {
                    "pack_id": pack["installation_id"],
                    "pack_name": pack["name"],
                    "relationship_type": "manages"
                }
                for pack in packs
            ]
        except Exception as e:
            logger.warning(f"Error finding agent packs for profile {artifact_id}: {e}")
            return []


class McpServerDetector(BaseDetector):
    """Detects relationships for MCP server configurations."""

    async def find_sessions(
        self,
        artifact_id: str,
        user_uuid: str,
        include_archived: bool = False
    ) -> Dict[str, Any]:
        """
        Find sessions using profiles that reference this MCP server.

        Sessions don't directly reference MCP servers - the relationship is:
        Session → Profile → MCP Server
        """
        from trusted_data_agent.core.session_manager import SESSIONS_DIR
        import aiofiles

        # First find profiles using this MCP server
        profiles_with_server = await self.find_profiles(artifact_id, user_uuid)
        profile_ids_with_server = {p["profile_id"] for p in profiles_with_server}

        if not profile_ids_with_server:
            return {"active": [], "archived": []}

        active_sessions = []
        archived_sessions = []
        user_session_dir = Path(SESSIONS_DIR) / user_uuid
        if not user_session_dir.exists():
            return {"active": [], "archived": []}

        for session_file in user_session_dir.glob("*.json"):
            try:
                async with aiofiles.open(session_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    session_data = json.loads(content)

                session_profile_id = session_data.get("profile_id")

                # Check if session is archived
                is_session_archived = session_data.get("is_archived") or session_data.get("archived")

                # Skip archived sessions if not requested
                if is_session_archived and not include_archived:
                    continue

                if session_profile_id in profile_ids_with_server:
                    # Find which profile to show in details
                    profile_info = next(
                        (p for p in profiles_with_server if p["profile_id"] == session_profile_id),
                        None
                    )
                    profile_tag = profile_info.get("profile_tag", "") if profile_info else ""

                    session_info = {
                        "session_id": session_data.get("id"),
                        "session_name": session_data.get("name", "Unnamed Session"),
                        "relationship_type": "profile_mcp_server",
                        "details": f"Uses profile @{profile_tag} which connects to this MCP server",
                        "is_archived": bool(is_session_archived)
                    }

                    if is_session_archived:
                        archived_sessions.append(session_info)
                    else:
                        active_sessions.append(session_info)

            except Exception as e:
                logger.warning(f"Error checking session {session_file}: {e}")
                continue

        return {
            "active": active_sessions,
            "archived": archived_sessions
        }

    async def find_profiles(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """Find profiles that reference this MCP server."""
        from trusted_data_agent.core.config_manager import get_config_manager

        config_manager = get_config_manager()
        user_profiles = config_manager.get_profiles(user_uuid)

        profiles_found = []

        for profile in user_profiles:
            # Check both possible field names
            mcp_server_id = profile.get("mcpServerId") or profile.get("mcp_server_id")

            if mcp_server_id and str(mcp_server_id) == str(artifact_id):
                profiles_found.append({
                    "profile_id": profile.get("id"),
                    "profile_name": profile.get("name", "Unknown Profile"),
                    "profile_tag": profile.get("tag", ""),
                    "relationship_type": "mcp_connection"
                })

        return profiles_found

    async def find_agent_packs(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """MCP servers aren't managed by agent packs (return empty)."""
        return []


class LlmConfigDetector(BaseDetector):
    """Detects relationships for LLM configurations."""

    async def find_sessions(
        self,
        artifact_id: str,
        user_uuid: str,
        include_archived: bool = False
    ) -> Dict[str, Any]:
        """
        Find sessions using profiles that reference this LLM config.

        Sessions don't directly reference LLM configs - the relationship is:
        Session → Profile → LLM Config
        """
        from trusted_data_agent.core.session_manager import SESSIONS_DIR
        import aiofiles

        # First find profiles using this LLM config
        profiles_with_config = await self.find_profiles(artifact_id, user_uuid)
        profile_ids_with_config = {p["profile_id"] for p in profiles_with_config}

        if not profile_ids_with_config:
            return {"active": [], "archived": []}

        active_sessions = []
        archived_sessions = []
        user_session_dir = Path(SESSIONS_DIR) / user_uuid
        if not user_session_dir.exists():
            return {"active": [], "archived": []}

        for session_file in user_session_dir.glob("*.json"):
            try:
                async with aiofiles.open(session_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    session_data = json.loads(content)

                session_profile_id = session_data.get("profile_id")

                # Check if session is archived
                is_session_archived = session_data.get("is_archived") or session_data.get("archived")

                # Skip archived sessions if not requested
                if is_session_archived and not include_archived:
                    continue

                if session_profile_id in profile_ids_with_config:
                    profile_info = next(
                        (p for p in profiles_with_config if p["profile_id"] == session_profile_id),
                        None
                    )
                    profile_tag = profile_info.get("profile_tag", "") if profile_info else ""

                    session_info = {
                        "session_id": session_data.get("id"),
                        "session_name": session_data.get("name", "Unnamed Session"),
                        "relationship_type": "profile_llm_config",
                        "details": f"Uses profile @{profile_tag} which connects to this LLM configuration",
                        "is_archived": bool(is_session_archived)
                    }

                    if is_session_archived:
                        archived_sessions.append(session_info)
                    else:
                        active_sessions.append(session_info)

            except Exception as e:
                logger.warning(f"Error checking session {session_file}: {e}")
                continue

        return {
            "active": active_sessions,
            "archived": archived_sessions
        }

    async def find_profiles(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """Find profiles that reference this LLM configuration."""
        from trusted_data_agent.core.config_manager import get_config_manager

        config_manager = get_config_manager()
        user_profiles = config_manager.get_profiles(user_uuid)

        profiles_found = []

        for profile in user_profiles:
            # Check both possible field names
            llm_config_id = profile.get("llmConfigurationId") or profile.get("llm_config_id")

            if llm_config_id and str(llm_config_id) == str(artifact_id):
                profiles_found.append({
                    "profile_id": profile.get("id"),
                    "profile_name": profile.get("name", "Unknown Profile"),
                    "profile_tag": profile.get("tag", ""),
                    "relationship_type": "llm_provider"
                })

        return profiles_found

    async def find_agent_packs(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """LLM configs aren't managed by agent packs (return empty)."""
        return []


class AgentPackDetector(BaseDetector):
    """Detects relationships for agent pack installations."""

    async def find_sessions(
        self,
        artifact_id: str,
        user_uuid: str,
        include_archived: bool = False
    ) -> Dict[str, Any]:
        """
        Find sessions using resources managed by this agent pack.

        Agent packs manage profiles and collections. Sessions use those resources.
        """
        from trusted_data_agent.core.agent_pack_db import AgentPackDB
        from trusted_data_agent.core.session_manager import SESSIONS_DIR
        import aiofiles

        # Get all resources managed by this pack
        pack_db = AgentPackDB()
        try:
            pack_id = int(artifact_id)
            resources = pack_db.get_resources_for_pack(pack_id)
        except (ValueError, TypeError):
            logger.error(f"Invalid agent pack ID: {artifact_id}")
            return {"active": [], "archived": []}

        managed_profile_ids = {
            r["resource_id"] for r in resources if r["resource_type"] == "profile"
        }
        managed_collection_ids = {
            str(r["resource_id"]) for r in resources if r["resource_type"] == "collection"
        }

        if not managed_profile_ids and not managed_collection_ids:
            return {"active": [], "archived": []}

        active_sessions = []
        archived_sessions = []
        user_session_dir = Path(SESSIONS_DIR) / user_uuid
        if not user_session_dir.exists():
            return {"active": [], "archived": []}

        for session_file in user_session_dir.glob("*.json"):
            try:
                async with aiofiles.open(session_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    session_data = json.loads(content)

                session_id = session_data.get("id")
                session_name = session_data.get("name", "Unnamed Session")
                session_profile_id = session_data.get("profile_id")
                rag_collection_id = session_data.get("rag_collection_id")

                # Check if session is archived
                is_session_archived = session_data.get("is_archived") or session_data.get("archived")

                # Skip archived sessions if not requested
                if is_session_archived and not include_archived:
                    continue

                session_added = False

                # Check if session uses a managed profile
                if session_profile_id in managed_profile_ids:
                    session_info = {
                        "session_id": session_id,
                        "session_name": session_name,
                        "relationship_type": "uses_pack_profile",
                        "details": "Uses a profile managed by this agent pack",
                        "is_archived": bool(is_session_archived)
                    }

                    if is_session_archived:
                        archived_sessions.append(session_info)
                    else:
                        active_sessions.append(session_info)
                    session_added = True

                # Check if session uses a managed collection (if not already added)
                if not session_added and rag_collection_id and str(rag_collection_id) in managed_collection_ids:
                    session_info = {
                        "session_id": session_id,
                        "session_name": session_name,
                        "relationship_type": "uses_pack_collection",
                        "details": "Uses a collection managed by this agent pack",
                        "is_archived": bool(is_session_archived)
                    }

                    if is_session_archived:
                        archived_sessions.append(session_info)
                    else:
                        active_sessions.append(session_info)

            except Exception as e:
                logger.warning(f"Error checking session {session_file}: {e}")
                continue

        return {
            "active": active_sessions,
            "archived": archived_sessions
        }

    async def find_profiles(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """Find profiles managed by this agent pack."""
        from trusted_data_agent.core.agent_pack_db import AgentPackDB
        from trusted_data_agent.core.config_manager import get_config_manager

        pack_db = AgentPackDB()
        try:
            pack_id = int(artifact_id)
            resources = pack_db.get_resources_for_pack(pack_id)
        except (ValueError, TypeError):
            logger.error(f"Invalid agent pack ID: {artifact_id}")
            return []

        managed_profile_ids = {
            r["resource_id"] for r in resources if r["resource_type"] == "profile"
        }

        if not managed_profile_ids:
            return []

        config_manager = get_config_manager()
        user_profiles = config_manager.get_profiles(user_uuid)

        profiles_found = []
        for profile in user_profiles:
            if profile.get("id") in managed_profile_ids:
                profiles_found.append({
                    "profile_id": profile.get("id"),
                    "profile_name": profile.get("name", "Unknown Profile"),
                    "profile_tag": profile.get("tag", ""),
                    "relationship_type": "managed_by_pack"
                })

        return profiles_found

    async def find_agent_packs(
        self,
        artifact_id: str,
        user_uuid: str
    ) -> List[Dict[str, Any]]:
        """Agent packs don't reference other agent packs (return empty)."""
        return []


# Detector registry
DETECTORS = {
    "collection": CollectionDetector,
    "profile": ProfileDetector,
    "agent-pack": AgentPackDetector,
    "mcp-server": McpServerDetector,
    "llm-config": LlmConfigDetector,
}


def get_detector(artifact_type: str) -> BaseDetector:
    """Get the appropriate detector for an artifact type."""
    detector_class = DETECTORS.get(artifact_type)
    if not detector_class:
        raise ValueError(f"Unsupported artifact type: {artifact_type}")
    return detector_class()
