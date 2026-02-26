"""
Base class and data structures for canvas execution connectors.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionResult:
    """Result from executing code via a connector."""
    result: str | None = None
    error: str | None = None
    row_count: int = 0
    execution_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectionTestResult:
    """Result from testing a database connection."""
    valid: bool = False
    message: str = ''
    server_info: str | None = None


class BaseCanvasConnector(ABC):
    """Abstract base class for canvas execution connectors."""

    id: str = ''
    name: str = ''
    supported_drivers: list[str] = []

    @abstractmethod
    async def execute(self, code: str, credentials: dict) -> ExecutionResult:
        """Execute code with the given credentials."""
        ...

    @abstractmethod
    async def test_connection(self, credentials: dict) -> ConnectionTestResult:
        """Test whether credentials can establish a connection."""
        ...
