"""
uderia-slack MCP Server

Provides Slack tools via stdio transport.
The bot token is passed via environment variable (injected by the platform
from the per-user OAuth token stored in messaging_identities).

Tools:
    list_channels   — list public channels in the workspace
    get_messages    — get recent messages from a channel
    send_message    — post a message to a channel
    search_messages — search messages across the workspace
    list_users      — list workspace members

Configuration (env vars injected by platform per-user):
    SLACK_BOT_TOKEN   — Slack bot OAuth token
    SLACK_USER_TOKEN  — Slack user OAuth token (for search)

Dependencies:
    httpx
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("uderia-slack")

BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
USER_TOKEN = os.environ.get("SLACK_USER_TOKEN", "")
_SLACK_API = "https://slack.com/api"


def _check_credentials() -> str | None:
    if not BOT_TOKEN:
        return "Slack workspace not connected. Connect via Platform Components → Connectors → uderia-slack."
    return None


def _bot_headers() -> dict:
    return {"Authorization": f"Bearer {BOT_TOKEN}", "Content-Type": "application/json; charset=utf-8"}


def _user_headers() -> dict:
    token = USER_TOKEN or BOT_TOKEN
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}


async def _api_get(endpoint: str, params: dict, use_user_token: bool = False) -> dict:
    import httpx
    headers = _user_headers() if use_user_token else _bot_headers()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{_SLACK_API}/{endpoint}", headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
    return data


async def _api_post(endpoint: str, payload: dict) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{_SLACK_API}/{endpoint}", headers=_bot_headers(), json=payload)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
    return data


async def tool_list_channels(max_results: int = 50, include_private: bool = False) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    try:
        types = "public_channel,private_channel" if include_private else "public_channel"
        data = await _api_get("conversations.list", {
            "limit": min(max_results, 200),
            "types": types,
            "exclude_archived": True,
        })
        channels = []
        for ch in data.get("channels", []):
            channels.append({
                "id": ch.get("id"),
                "name": ch.get("name"),
                "is_private": ch.get("is_private", False),
                "is_member": ch.get("is_member", False),
                "num_members": ch.get("num_members", 0),
                "topic": ch.get("topic", {}).get("value", ""),
            })
        return json.dumps({"channels": channels, "count": len(channels)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_get_messages(channel_id: str, max_results: int = 20) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    try:
        data = await _api_get("conversations.history", {
            "channel": channel_id,
            "limit": min(max_results, 100),
        })
        messages = []
        for m in data.get("messages", []):
            if m.get("type") == "message" and not m.get("subtype"):
                messages.append({
                    "ts": m.get("ts"),
                    "user": m.get("user", ""),
                    "text": m.get("text", ""),
                    "thread_ts": m.get("thread_ts"),
                    "reply_count": m.get("reply_count", 0),
                })
        return json.dumps({"channel_id": channel_id, "messages": messages, "count": len(messages)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_send_message(channel_id: str, message: str, thread_ts: str = None) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    try:
        payload = {"channel": channel_id, "text": message}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        data = await _api_post("chat.postMessage", payload)
        return json.dumps({
            "sent": True,
            "ts": data.get("ts"),
            "channel": data.get("channel"),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_search_messages(query: str, max_results: int = 20) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    try:
        data = await _api_get("search.messages", {
            "query": query,
            "count": min(max_results, 100),
            "sort": "timestamp",
            "sort_dir": "desc",
        }, use_user_token=True)
        matches = data.get("messages", {}).get("matches", [])
        results = []
        for m in matches:
            results.append({
                "ts": m.get("ts"),
                "channel_id": m.get("channel", {}).get("id", ""),
                "channel_name": m.get("channel", {}).get("name", ""),
                "user": m.get("username", ""),
                "text": m.get("text", ""),
                "permalink": m.get("permalink", ""),
            })
        return json.dumps({"query": query, "results": results, "count": len(results)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_list_users(max_results: int = 50) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    try:
        data = await _api_get("users.list", {"limit": min(max_results, 200)})
        users = []
        for u in data.get("members", []):
            if u.get("deleted") or u.get("is_bot"):
                continue
            profile = u.get("profile", {})
            users.append({
                "id": u.get("id"),
                "name": u.get("name"),
                "display_name": profile.get("display_name") or u.get("real_name", ""),
                "email": profile.get("email", ""),
                "is_admin": u.get("is_admin", False),
            })
        return json.dumps({"users": users, "count": len(users)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP stdio protocol ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "list_channels",
        "description": "List public channels in the connected Slack workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Maximum number of channels (default: 50, max: 200).", "minimum": 1, "maximum": 200},
                "include_private": {"type": "boolean", "description": "Include private channels (requires bot to be a member). Default: false."},
            },
        },
    },
    {
        "name": "get_messages",
        "description": "Get recent messages from a Slack channel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Slack channel ID (from list_channels)."},
                "max_results": {"type": "integer", "description": "Maximum number of messages (default: 20, max: 100).", "minimum": 1, "maximum": 100},
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "send_message",
        "description": "Post a message to a Slack channel or thread.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Slack channel ID."},
                "message": {"type": "string", "description": "Message text to send. Supports Slack mrkdwn formatting."},
                "thread_ts": {"type": "string", "description": "Thread timestamp to reply to (optional). Omit for a new top-level message."},
            },
            "required": ["channel_id", "message"],
        },
    },
    {
        "name": "search_messages",
        "description": "Search messages across the Slack workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query. Supports Slack search modifiers (in:#channel, from:@user, etc.)."},
                "max_results": {"type": "integer", "description": "Maximum results (default: 20, max: 100).", "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_users",
        "description": "List members of the connected Slack workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Maximum number of users (default: 50, max: 200).", "minimum": 1, "maximum": 200},
            },
        },
    },
]

TOOL_HANDLERS = {
    "list_channels": tool_list_channels,
    "get_messages": tool_get_messages,
    "send_message": tool_send_message,
    "search_messages": tool_search_messages,
    "list_users": tool_list_users,
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
                "serverInfo": {"name": "uderia-slack", "version": "1.0.0"},
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
