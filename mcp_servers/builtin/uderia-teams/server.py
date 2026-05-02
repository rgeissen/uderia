"""
uderia-teams MCP Server

Provides Microsoft Teams tools via stdio transport.
User credentials are passed via environment variables (injected by the platform
from the per-user OAuth token stored in messaging_identities).

Tools:
    list_teams      — list teams the user is a member of
    list_channels   — list channels in a team
    get_messages    — get recent messages from a channel
    send_message    — post a message to a channel
    create_meeting  — create an online meeting (Teams link)

Configuration (env vars injected by platform per-user):
    MS_TEAMS_ACCESS_TOKEN   — user's OAuth access token
    MS_TEAMS_REFRESH_TOKEN  — user's OAuth refresh token

Dependencies:
    httpx
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("uderia-teams")

ACCESS_TOKEN = os.environ.get("MS_TEAMS_ACCESS_TOKEN", "")
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _check_credentials() -> str | None:
    if not ACCESS_TOKEN:
        return "Microsoft account not connected. Connect via Platform Components → Connectors → uderia-teams."
    return None


def _headers() -> dict:
    return {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}


async def tool_list_teams(max_results: int = 20) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/me/joinedTeams",
                headers=_headers(),
                params={"$top": min(max_results, 50)},
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        teams = [
            {"id": t.get("id"), "name": t.get("displayName"), "description": t.get("description", "")}
            for t in data.get("value", [])
        ]
        return json.dumps({"teams": teams, "count": len(teams)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_list_channels(team_id: str, max_results: int = 50) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/teams/{team_id}/channels",
                headers=_headers(),
                params={"$top": min(max_results, 200)},
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        channels = [
            {
                "id": c.get("id"),
                "name": c.get("displayName"),
                "description": c.get("description", ""),
                "is_general": c.get("displayName", "").lower() == "general",
            }
            for c in data.get("value", [])
        ]
        return json.dumps({"team_id": team_id, "channels": channels, "count": len(channels)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_get_messages(team_id: str, channel_id: str, max_results: int = 20) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages",
                headers=_headers(),
                params={"$top": min(max_results, 50)},
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        messages = []
        for m in data.get("value", []):
            body = m.get("body", {})
            from_user = m.get("from", {}).get("user", {})
            messages.append({
                "id": m.get("id"),
                "created_at": m.get("createdDateTime"),
                "from": from_user.get("displayName", ""),
                "content": body.get("content", ""),
                "content_type": body.get("contentType", "text"),
            })
        return json.dumps({"team_id": team_id, "channel_id": channel_id, "messages": messages, "count": len(messages)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_send_message(team_id: str, channel_id: str, message: str) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        payload = {"body": {"content": message, "contentType": "text"}}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages",
                headers=_headers(),
                json=payload,
            )
        if resp.status_code not in (200, 201):
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        result = resp.json()
        return json.dumps({
            "sent": True,
            "message_id": result.get("id"),
            "created_at": result.get("createdDateTime"),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_create_meeting(
    subject: str,
    start_datetime: str,
    end_datetime: str,
    attendees: list[str] = None,
) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        payload = {
            "subject": subject,
            "startDateTime": start_datetime,
            "endDateTime": end_datetime,
        }
        if attendees:
            payload["participants"] = {
                "attendees": [
                    {"upn": email, "role": "attendee"}
                    for email in attendees
                ]
            }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_GRAPH_BASE}/me/onlineMeetings",
                headers=_headers(),
                json=payload,
            )
        if resp.status_code not in (200, 201):
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        result = resp.json()
        return json.dumps({
            "created": True,
            "meeting_id": result.get("id"),
            "join_url": result.get("joinWebUrl"),
            "subject": result.get("subject"),
            "start": result.get("startDateTime"),
            "end": result.get("endDateTime"),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP stdio protocol ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "list_teams",
        "description": "List Microsoft Teams the user is a member of.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Maximum number of teams (default: 20, max: 50).", "minimum": 1, "maximum": 50},
            },
        },
    },
    {
        "name": "list_channels",
        "description": "List channels in a Microsoft Teams team.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Teams team ID (from list_teams)."},
                "max_results": {"type": "integer", "description": "Maximum number of channels (default: 50).", "minimum": 1, "maximum": 200},
            },
            "required": ["team_id"],
        },
    },
    {
        "name": "get_messages",
        "description": "Get recent messages from a Microsoft Teams channel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Teams team ID."},
                "channel_id": {"type": "string", "description": "Channel ID (from list_channels)."},
                "max_results": {"type": "integer", "description": "Maximum number of messages (default: 20, max: 50).", "minimum": 1, "maximum": 50},
            },
            "required": ["team_id", "channel_id"],
        },
    },
    {
        "name": "send_message",
        "description": "Post a text message to a Microsoft Teams channel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Teams team ID."},
                "channel_id": {"type": "string", "description": "Channel ID."},
                "message": {"type": "string", "description": "Message text to send."},
            },
            "required": ["team_id", "channel_id", "message"],
        },
    },
    {
        "name": "create_meeting",
        "description": "Create a Microsoft Teams online meeting and get the join link.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Meeting subject / title."},
                "start_datetime": {"type": "string", "description": "Start time in ISO 8601 format, e.g. 2026-05-15T10:00:00+02:00."},
                "end_datetime": {"type": "string", "description": "End time in ISO 8601 format."},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee email addresses / UPNs (optional)."},
            },
            "required": ["subject", "start_datetime", "end_datetime"],
        },
    },
]

TOOL_HANDLERS = {
    "list_teams": tool_list_teams,
    "list_channels": tool_list_channels,
    "get_messages": tool_get_messages,
    "send_message": tool_send_message,
    "create_meeting": tool_create_meeting,
}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def handle_request(request: dict) -> dict | None:
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "uderia-teams", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOL_DEFINITIONS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return _error(req_id, -32601, f"Tool '{tool_name}' not found")
        try:
            result_text = await handler(**arguments)
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": result_text}]},
            }
        except Exception as exc:
            return _error(req_id, -32603, str(exc))

    if method == "notifications/initialized":
        return None

    return _error(req_id, -32601, f"Method '{method}' not found")


async def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_event_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            request = json.loads(line.decode("utf-8").strip())
            response = await handle_request(request)
            if response is not None:
                _send(response)
        except json.JSONDecodeError:
            continue
        except Exception as exc:
            logger.error("Unhandled error: %s", exc)


if __name__ == "__main__":
    asyncio.run(main())
