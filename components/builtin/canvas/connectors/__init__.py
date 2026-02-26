"""
Canvas Connector Registry (Backend).

Provides execution connectors for the canvas component.
Each connector handles a specific database driver or execution environment.
"""

from .base import BaseCanvasConnector, ExecutionResult, ConnectionTestResult
from .sql import SQLNativeConnector

# Registry of available backend connectors
_CONNECTORS = {
    'sql_native': SQLNativeConnector,
}


def get_connector(connector_id: str) -> BaseCanvasConnector | None:
    """Get a connector instance by ID."""
    cls = _CONNECTORS.get(connector_id)
    if cls:
        return cls()
    return None


def list_connectors() -> list[str]:
    """List all registered connector IDs."""
    return list(_CONNECTORS.keys())
