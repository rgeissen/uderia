"""
Unified artifact relationship analyzer.

Provides a single entry point for analyzing relationships between
artifacts (collections, profiles, MCP servers, etc.) and sessions.
"""

from typing import Dict, Any, List
import logging

from trusted_data_agent.core.artifact_detectors import get_detector

logger = logging.getLogger("quart.app")


class RelationshipAnalyzer:
    """Analyzes relationships for any artifact type."""

    async def analyze_artifact_relationships(
        self,
        artifact_type: str,
        artifact_id: str,
        user_uuid: str,
        include_archived: bool = False,
        limit: int = 5,
        full: bool = False
    ) -> Dict[str, Any]:
        """
        Analyze all relationships for a given artifact.

        Args:
            artifact_type: Type of artifact (collection, profile, mcp-server, llm-config, agent-pack)
            artifact_id: ID of the artifact
            user_uuid: User who owns the artifact
            include_archived: Include archived sessions in results
            limit: Maximum sessions to return per relationship type
            full: Include extended relationship metadata

        Returns:
            Dict with relationships structure
        """
        try:
            detector = get_detector(artifact_type)

            # Find all relationships (returns {"active": [...], "archived": [...]})
            sessions_result = await detector.find_sessions(artifact_id, user_uuid, include_archived)
            active_sessions = sessions_result.get("active", [])
            archived_sessions = sessions_result.get("archived", [])

            profiles = await detector.find_profiles(artifact_id, user_uuid)
            agent_packs = await detector.find_agent_packs(artifact_id, user_uuid)

            # Combine sessions for display (active always shown, archived only if requested)
            all_sessions = active_sessions + (archived_sessions if include_archived else [])

            # Apply limit to displayed sessions
            limited_sessions = all_sessions[:limit]
            has_more_sessions = len(all_sessions) > limit

            # Build response with active/archived counts
            relationships = {
                "sessions": {
                    "active_count": len(active_sessions),
                    "archived_count": len(archived_sessions),
                    "total_count": len(active_sessions) + len(archived_sessions),
                    "items": limited_sessions,
                    "limit_applied": limit < len(all_sessions),
                    "has_more": has_more_sessions
                },
                "profiles": {
                    "count": len(profiles),
                    "items": profiles
                },
                "agent_packs": {
                    "count": len(agent_packs),
                    "items": agent_packs
                }
            }

            # Add deletion safety analysis
            deletion_info = await self.analyze_deletion_safety(
                artifact_type,
                user_uuid,
                relationships,
                agent_packs
            )

            return {
                "relationships": relationships,
                "deletion_info": deletion_info
            }

        except Exception as e:
            logger.error(f"Error analyzing relationships for {artifact_type} {artifact_id}: {e}", exc_info=True)
            raise

    async def analyze_deletion_safety(
        self,
        artifact_type: str,
        user_uuid: str,
        relationships: Dict[str, Any],
        agent_packs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze whether an artifact can be safely deleted.

        Args:
            artifact_type: Type of artifact being analyzed
            user_uuid: User who owns the artifact (needed for default profile check)
            relationships: Relationships dict from find_* methods
            agent_packs: List of agent packs that manage this artifact

        Returns:
            Dict with deletion safety information
        """
        sessions_info = relationships["sessions"]
        active_count = sessions_info["active_count"]
        archived_count = sessions_info["archived_count"]
        total_count = sessions_info["total_count"]

        profiles = relationships["profiles"]["items"]

        # Check for blockers
        blockers = []
        warnings = []

        # Agent pack blocker (for collections, profiles, etc. managed by packs)
        if agent_packs:
            pack_names = ", ".join(p["pack_name"] for p in agent_packs)
            blockers.append({
                "type": "agent_pack",
                "message": f"This {artifact_type} is managed by agent pack(s): {pack_names}. "
                           f"Uninstall the pack(s) to remove it."
            })

        # For agent-packs: check if any managed profile is the default profile
        if artifact_type == "agent-pack" and profiles:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            default_profile_id = config_manager.get_default_profile_id(user_uuid)

            if default_profile_id:
                for profile in profiles:
                    if profile.get("profile_id") == default_profile_id:
                        blockers.append({
                            "type": "default_profile",
                            "message": f"This pack contains the default profile '@{profile.get('profile_tag', 'unknown')}'. "
                                       f"Please change the default profile first, then try uninstalling again."
                        })
                        break

        # Session archiving warning (only for ACTIVE sessions)
        if active_count > 0:
            warnings.append(
                f"{active_count} active session{'s' if active_count != 1 else ''} will be archived"
            )

        # Informational: Archived sessions also reference this
        if archived_count > 0:
            warnings.append(
                f"{archived_count} already-archived session{'s' if archived_count != 1 else ''} also "
                f"reference{'s' if archived_count == 1 else ''} this {artifact_type}"
            )

        # Profile impact warning
        if profiles:
            count = len(profiles)
            warnings.append(
                f"{count} profile{'s' if count != 1 else ''} will lose access to this {artifact_type}"
            )

        return {
            "can_delete": len(blockers) == 0,
            "blockers": blockers,
            "warnings": warnings,
            "cascade_effects": {
                "active_sessions_archived": active_count,
                "archived_sessions_affected": archived_count,
                "total_sessions_affected": total_count,
                "profiles_affected": len(profiles)
            }
        }
