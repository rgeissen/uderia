"""
Connector registry — maps platform names to their connector modules.

A connector is a per-user OAuth integration. Each connector must expose:
    initiate_oauth(user_uuid, redirect_uri) -> Optional[str]
    handle_callback(code, state, redirect_uri) -> Optional[dict]
    get_connection_status(user_uuid) -> dict
    disconnect(user_uuid) -> None
    get_tokens(user_uuid) -> Optional[dict]          # async
    is_configured() -> bool
    SERVER_ID: str                                    # platform_connectors.id

The registry is keyed by the platform name stored in messaging_identities.platform
(e.g. "google").  Adding a new connector only requires:
  1. Create src/trusted_data_agent/connectors/<name>_connector.py
  2. Register it here.
"""

from typing import Any, Optional

_REGISTRY: dict[str, Any] = {}


def register(platform: str, module: Any):
    _REGISTRY[platform] = module


def get(platform: str) -> Optional[Any]:
    return _REGISTRY.get(platform)


def all_platforms() -> list[str]:
    return list(_REGISTRY.keys())


def server_id_to_platform(server_id: str) -> Optional[str]:
    """Return the platform name for a given platform_connectors.id, or None."""
    for platform, mod in _REGISTRY.items():
        if getattr(mod, "SERVER_ID", None) == server_id:
            return platform
    return None


# ── Register built-in connectors ──────────────────────────────────────────────

from trusted_data_agent.connectors import google_connector as _google
register("google", _google)

from trusted_data_agent.connectors import teams_connector as _teams
register("teams", _teams)

from trusted_data_agent.connectors import outlook_connector as _outlook
register("outlook", _outlook)

from trusted_data_agent.connectors import slack_connector as _slack
register("slack", _slack)

from trusted_data_agent.connectors import sharepoint_connector as _sharepoint
register("sharepoint", _sharepoint)
