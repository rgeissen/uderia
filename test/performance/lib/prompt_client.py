"""
HTTP client for Uderia REST API — used by mcp_tool_test.py and mcp_prompt_test.py.

Provides authentication, session management, query submission, task polling,
and tool/prompt discovery against a running Uderia server.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

import requests


class PromptClientError(Exception):
    """Raised for any client-level error (auth, network, timeout, API errors)."""
    pass


@dataclass
class ToolInfo:
    """Metadata for a discovered MCP tool."""
    name: str
    description: str = ""
    arguments: list = field(default_factory=list)
    scope: str = "global"
    disabled: bool = False


@dataclass
class PromptInfo:
    """Metadata for a discovered MCP prompt."""
    name: str
    description: str = ""
    arguments: list = field(default_factory=list)
    disabled: bool = False


@dataclass
class TaskResult:
    """Result of polling a completed task."""
    task_id: str
    status: str = "unknown"
    events: list = field(default_factory=list)
    result: dict = field(default_factory=dict)
    duration_ms: int = 0
    session_id: str = ""


# Scope hierarchy — mirrors AppConfig.TOOL_SCOPE_HIERARCHY in config.py
_SCOPE_ARGS = {
    "column": {"database_name", "object_name", "column_name",
               "db_name", "table_name", "col_name"},
    "table": {"database_name", "object_name",
              "db_name", "table_name", "tablename"},
    "database": {"database_name", "db_name"},
}


def _infer_scope(arguments: list) -> str:
    """Infer tool scope from its required arguments."""
    required_names = {
        a["name"].lower()
        for a in arguments
        if a.get("required")
    }
    # Check from most specific to least
    col_indicators = {"column_name", "col_name", "columnname"}
    table_indicators = {"object_name", "table_name", "tablename", "obj_name"}
    db_indicators = {"database_name", "db_name", "databasename"}

    if required_names & col_indicators:
        return "column"
    if required_names & table_indicators:
        return "table"
    if required_names & db_indicators:
        return "database"
    return "global"


class PromptClient:
    """Synchronous HTTP client for the Uderia REST API."""

    def __init__(self, base_url: str = "http://localhost:5050"):
        self.base_url = base_url.rstrip("/")
        self.jwt_token: Optional[str] = None
        self.user_uuid: Optional[str] = None
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.jwt_token:
            h["Authorization"] = f"Bearer {self.jwt_token}"
        return h

    def _get(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.get(url, headers=self._headers(), timeout=30, **kwargs)
        except requests.RequestException as e:
            raise PromptClientError(f"GET {path} failed: {e}")
        return resp

    def _post(self, path: str, json_body: dict = None, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.post(
                url, headers=self._headers(), json=json_body, timeout=30, **kwargs
            )
        except requests.RequestException as e:
            raise PromptClientError(f"POST {path} failed: {e}")
        return resp

    def _check(self, resp: requests.Response, context: str):
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("message") or resp.json().get("error") or resp.text
            except Exception:
                detail = resp.text[:200]
            raise PromptClientError(f"{context}: HTTP {resp.status_code} — {detail}")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, username: str, password: str) -> None:
        """POST /api/v1/auth/login — store JWT token and user_uuid."""
        resp = self._post("/api/v1/auth/login", {"username": username, "password": password})
        self._check(resp, "Authentication")
        data = resp.json()
        self.jwt_token = data.get("token")
        user = data.get("user", {})
        self.user_uuid = user.get("user_uuid") or user.get("id")
        if not self.jwt_token:
            raise PromptClientError("Login succeeded but no token in response")

    # ------------------------------------------------------------------
    # Profile operations
    # ------------------------------------------------------------------

    def get_all_profiles(self) -> list:
        """GET /api/v1/profiles — return raw profile list."""
        resp = self._get("/api/v1/profiles")
        self._check(resp, "Get profiles")
        return resp.json().get("profiles", [])

    def find_profile_by_tag(self, tag: str) -> Optional[str]:
        """Find profile_id by tag string (strips leading '@')."""
        tag = tag.lstrip("@").upper()
        profiles = self.get_all_profiles()
        for p in profiles:
            if (p.get("tag") or "").upper() == tag:
                return p["id"]
        return None

    def get_profile_details(self, tag: str) -> Optional[dict]:
        """Find full profile dict by tag string."""
        tag = tag.lstrip("@").upper()
        profiles = self.get_all_profiles()
        for p in profiles:
            if (p.get("tag") or "").upper() == tag:
                return p
        return None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_tools(self) -> dict:
        """Discover tools from the first tool-capable profile.
        Returns {category_name: [ToolInfo, ...]}."""
        profiles = self.get_all_profiles()

        # Find a profile that has MCP tools
        target = None
        for p in profiles:
            ptype = p.get("profile_type", "")
            if ptype == "tool_enabled" or (ptype == "llm_only" and p.get("useMcpTools")):
                target = p
                break
        if not target:
            raise PromptClientError("No tool-capable profile found")

        resp = self._get(f"/api/v1/profiles/{target['id']}/resources")
        self._check(resp, "Discover tools")
        data = resp.json()

        result = {}
        raw_tools = data.get("tools", {})
        for category, tools in raw_tools.items():
            infos = []
            for t in tools:
                args = []
                for a in t.get("arguments", []):
                    args.append({
                        "name": a.get("name", ""),
                        "type": a.get("type", "string"),
                        "description": a.get("description", ""),
                        "required": a.get("required", False),
                    })
                info = ToolInfo(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    arguments=args,
                    scope=_infer_scope(args),
                    disabled=t.get("disabled", False),
                )
                infos.append(info)
            result[category] = infos
        return result

    def discover_prompts(self) -> dict:
        """Discover prompts from the first tool-capable profile.
        Returns {category_name: [PromptInfo, ...]}."""
        profiles = self.get_all_profiles()
        target = None
        for p in profiles:
            ptype = p.get("profile_type", "")
            if ptype == "tool_enabled" or (ptype == "llm_only" and p.get("useMcpTools")):
                target = p
                break
        if not target:
            raise PromptClientError("No tool-capable profile found")

        resp = self._get(f"/api/v1/profiles/{target['id']}/resources")
        self._check(resp, "Discover prompts")
        data = resp.json()

        result = {}
        raw_prompts = data.get("prompts", {})
        for category, prompts in raw_prompts.items():
            infos = []
            for pr in prompts:
                args = []
                for a in pr.get("arguments", []):
                    args.append({
                        "name": a.get("name", ""),
                        "type": a.get("type", "string"),
                        "description": a.get("description", ""),
                        "required": a.get("required", False),
                    })
                info = PromptInfo(
                    name=pr.get("name", ""),
                    description=pr.get("description", ""),
                    arguments=args,
                    disabled=pr.get("disabled", False),
                )
                infos.append(info)
            result[category] = infos
        return result

    # ------------------------------------------------------------------
    # Session & query
    # ------------------------------------------------------------------

    def create_session(self) -> str:
        """POST /api/v1/sessions — return session_id."""
        resp = self._post("/api/v1/sessions", {})
        self._check(resp, "Create session")
        sid = resp.json().get("session_id")
        if not sid:
            raise PromptClientError("Session created but no session_id in response")
        return sid

    def submit_query(
        self,
        session_id: str,
        query: str,
        profile_id: str = None,
    ) -> str:
        """Submit a natural language query. Returns task_id."""
        body = {"prompt": query}
        if profile_id:
            body["profile_id"] = profile_id
        resp = self._post(f"/api/v1/sessions/{session_id}/query", body)
        self._check(resp, "Submit query")
        tid = resp.json().get("task_id")
        if not tid:
            raise PromptClientError("Query submitted but no task_id in response")
        return tid

    def submit_prompt_query(
        self,
        session_id: str,
        prompt_name: str,
        prompt_arguments: dict,
        profile_id: str = None,
    ) -> str:
        """Submit a query that invokes an MCP prompt. Returns task_id."""
        # The prompt field is required — build a human-readable wrapper
        arg_summary = ", ".join(f"{k}={v}" for k, v in prompt_arguments.items())
        body = {
            "prompt": f"Execute MCP prompt {prompt_name} with: {arg_summary}",
            "prompt_name": prompt_name,
            "prompt_arguments": prompt_arguments,
        }
        if profile_id:
            body["profile_id"] = profile_id
        resp = self._post(f"/api/v1/sessions/{session_id}/query", body)
        self._check(resp, "Submit prompt query")
        tid = resp.json().get("task_id")
        if not tid:
            raise PromptClientError("Prompt query submitted but no task_id in response")
        return tid

    # ------------------------------------------------------------------
    # Task polling
    # ------------------------------------------------------------------

    def poll_task(
        self,
        task_id: str,
        timeout: int = 180,
        interval: float = 2.0,
    ) -> TaskResult:
        """Poll GET /api/v1/tasks/{task_id} until done or timeout."""
        start = time.time()
        terminal_states = {"complete", "error", "cancelled"}

        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise PromptClientError(
                    f"Task {task_id} timed out after {timeout}s (last status: polling)"
                )

            resp = self._get(f"/api/v1/tasks/{task_id}")
            self._check(resp, f"Poll task {task_id}")
            data = resp.json()

            status = data.get("status", "unknown")
            if status in terminal_states:
                return TaskResult(
                    task_id=task_id,
                    status=status,
                    events=data.get("events", []),
                    result=data.get("result") or {},
                    duration_ms=int((time.time() - start) * 1000),
                )

            time.sleep(interval)

    # ------------------------------------------------------------------
    # Session data
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> dict:
        """GET /api/v1/sessions/{session_id}/details — return full session data including execution traces."""
        resp = self._get(f"/api/v1/sessions/{session_id}/details")
        self._check(resp, f"Get session {session_id}")
        return resp.json()
