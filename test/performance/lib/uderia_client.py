"""
Extended client for profile performance comparison tests.

Wraps PromptClient with profile-specific helpers used by
profile_performance_test.py.
"""

from dataclasses import dataclass
from typing import Optional

from prompt_client import PromptClient, PromptClientError, TaskResult


class UderiaClientError(Exception):
    """Raised for client errors in profile comparison tests."""
    pass


@dataclass
class Profile:
    id: str
    tag: str
    name: str
    profile_type: str
    provider: str = ""
    model: str = ""


class UderiaClient:
    """Client for profile comparison tests. Composes PromptClient."""

    def __init__(self, base_url: str = "http://localhost:5050"):
        self._client = PromptClient(base_url=base_url)

    @property
    def user_uuid(self) -> Optional[str]:
        return self._client.user_uuid

    def authenticate(self, username: str, password: str) -> None:
        try:
            self._client.authenticate(username, password)
        except PromptClientError as e:
            raise UderiaClientError(str(e))

    def find_profile_by_tag(self, tag: str) -> Optional[Profile]:
        """Find profile by tag, return Profile dataclass or None."""
        tag_clean = tag.lstrip("@").upper()
        try:
            profiles = self._client.get_all_profiles()
        except PromptClientError as e:
            raise UderiaClientError(str(e))

        for p in profiles:
            if (p.get("tag") or "").upper() == tag_clean:
                return Profile(
                    id=p["id"],
                    tag=p.get("tag", ""),
                    name=p.get("name", ""),
                    profile_type=p.get("profile_type", "tool_enabled"),
                    provider=p.get("providerName", ""),
                    model=p.get("model", ""),
                )
        return None

    def list_available_profiles(self) -> str:
        """Return formatted string of available profiles."""
        try:
            profiles = self._client.get_all_profiles()
        except PromptClientError:
            return "  (could not retrieve profiles)"

        lines = ["  Available profiles:"]
        for p in profiles:
            tag = p.get("tag", "?")
            name = p.get("name", "Unnamed")
            ptype = p.get("profile_type", "?")
            lines.append(f"    @{tag}: {name} ({ptype})")
        return "\n".join(lines)

    def create_session(self) -> str:
        try:
            return self._client.create_session()
        except PromptClientError as e:
            raise UderiaClientError(str(e))

    def submit_query(self, session_id: str, query: str, profile_id: str = None) -> str:
        try:
            return self._client.submit_query(session_id, query, profile_id)
        except PromptClientError as e:
            raise UderiaClientError(str(e))

    def poll_task(self, task_id: str, timeout: int = 60) -> TaskResult:
        try:
            return self._client.poll_task(task_id, timeout=timeout)
        except PromptClientError as e:
            raise UderiaClientError(str(e))

    def get_session_file(self, user_uuid: str, session_id: str) -> dict:
        """Get session data via REST API."""
        try:
            return self._client.get_session(session_id)
        except PromptClientError as e:
            raise UderiaClientError(str(e))
