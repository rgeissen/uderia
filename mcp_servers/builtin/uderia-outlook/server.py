"""
uderia-outlook MCP Server

Provides Microsoft Outlook (Mail + Calendar + Contacts) tools via stdio transport.
User credentials are passed via environment variables (injected by the platform
from the per-user OAuth token stored in messaging_identities).

Tools:
    read_emails     — list recent emails from inbox
    send_email      — send an email via Outlook
    search_emails   — search emails with an OData filter string
    list_calendar   — list upcoming calendar events
    create_event    — create a calendar event
    get_contacts    — search Outlook contacts

Configuration (env vars injected by platform per-user):
    MS_OUTLOOK_ACCESS_TOKEN   — user's OAuth access token
    MS_OUTLOOK_REFRESH_TOKEN  — user's OAuth refresh token

Dependencies:
    httpx
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("uderia-outlook")

ACCESS_TOKEN = os.environ.get("MS_OUTLOOK_ACCESS_TOKEN", "")
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _check_credentials() -> str | None:
    if not ACCESS_TOKEN:
        return "Microsoft account not connected. Connect via Platform Components → Connectors → uderia-outlook."
    return None


def _headers() -> dict:
    return {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}


async def tool_read_emails(max_results: int = 10, folder: str = "inbox") -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/me/mailFolders/{folder}/messages",
                headers=_headers(),
                params={
                    "$top": min(max_results, 50),
                    "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead",
                    "$orderby": "receivedDateTime desc",
                },
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        emails = []
        for m in data.get("value", []):
            sender = m.get("from", {}).get("emailAddress", {})
            emails.append({
                "id": m.get("id"),
                "subject": m.get("subject", ""),
                "from": sender.get("address", ""),
                "from_name": sender.get("name", ""),
                "received": m.get("receivedDateTime", ""),
                "preview": m.get("bodyPreview", ""),
                "is_read": m.get("isRead", True),
            })
        return json.dumps({"folder": folder, "emails": emails, "count": len(emails)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_send_email(to: str, subject: str, body: str, cc: str = "") -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        message = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": addr.strip()}} for addr in to.split(",") if addr.strip()],
        }
        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": addr.strip()}} for addr in cc.split(",") if addr.strip()]
        payload = {"message": message, "saveToSentItems": True}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_GRAPH_BASE}/me/sendMail",
                headers=_headers(),
                json=payload,
            )
        if resp.status_code not in (200, 202):
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        return json.dumps({"sent": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_search_emails(query: str, max_results: int = 10) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/me/messages",
                headers=_headers(),
                params={
                    "$search": f'"{query}"',
                    "$top": min(max_results, 50),
                    "$select": "id,subject,from,receivedDateTime,bodyPreview",
                },
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        emails = []
        for m in data.get("value", []):
            sender = m.get("from", {}).get("emailAddress", {})
            emails.append({
                "id": m.get("id"),
                "subject": m.get("subject", ""),
                "from": sender.get("address", ""),
                "received": m.get("receivedDateTime", ""),
                "preview": m.get("bodyPreview", ""),
            })
        return json.dumps({"query": query, "emails": emails, "count": len(emails)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_list_calendar(max_results: int = 10, time_min: str = None) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    from datetime import datetime, timezone
    try:
        start = time_min or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/me/calendarView",
                headers=_headers(),
                params={
                    "startDateTime": start,
                    "endDateTime": "2099-12-31T00:00:00Z",
                    "$top": min(max_results, 50),
                    "$select": "id,subject,start,end,location,bodyPreview,organizer",
                    "$orderby": "start/dateTime",
                },
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        events = []
        for ev in data.get("value", []):
            organizer = ev.get("organizer", {}).get("emailAddress", {})
            events.append({
                "id": ev.get("id"),
                "subject": ev.get("subject", ""),
                "start": ev.get("start", {}).get("dateTime", ""),
                "end": ev.get("end", {}).get("dateTime", ""),
                "location": ev.get("location", {}).get("displayName", ""),
                "organizer": organizer.get("address", ""),
                "preview": ev.get("bodyPreview", ""),
            })
        return json.dumps({"events": events, "count": len(events)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_create_event(
    subject: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
    attendees: list[str] = None,
) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        payload = {
            "subject": subject,
            "body": {"contentType": "Text", "content": description},
            "start": {"dateTime": start_datetime, "timeZone": "UTC"},
            "end": {"dateTime": end_datetime, "timeZone": "UTC"},
        }
        if location:
            payload["location"] = {"displayName": location}
        if attendees:
            payload["attendees"] = [
                {"emailAddress": {"address": a}, "type": "required"}
                for a in attendees
            ]
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_GRAPH_BASE}/me/events",
                headers=_headers(),
                json=payload,
            )
        if resp.status_code not in (200, 201):
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        result = resp.json()
        return json.dumps({
            "created": True,
            "event_id": result.get("id"),
            "web_link": result.get("webLink"),
            "teams_link": result.get("onlineMeeting", {}).get("joinUrl", ""),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_get_contacts(query: str, max_results: int = 10) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/me/contacts",
                headers=_headers(),
                params={
                    "$search": f'"{query}"',
                    "$top": min(max_results, 25),
                    "$select": "displayName,emailAddresses,businessPhones,mobilePhone",
                },
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        contacts = []
        for c in data.get("value", []):
            contacts.append({
                "name": c.get("displayName", ""),
                "emails": [e.get("address", "") for e in c.get("emailAddresses", [])],
                "phones": c.get("businessPhones", []) + ([c.get("mobilePhone")] if c.get("mobilePhone") else []),
            })
        return json.dumps({"query": query, "contacts": contacts, "count": len(contacts)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP stdio protocol ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "read_emails",
        "description": "Read recent emails from the user's Outlook inbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Maximum number of emails (default: 10, max: 50).", "minimum": 1, "maximum": 50},
                "folder": {"type": "string", "description": "Mail folder name (default: inbox)."},
            },
        },
    },
    {
        "name": "send_email",
        "description": "Send an email via the user's Outlook account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address(es), comma-separated."},
                "subject": {"type": "string", "description": "Email subject."},
                "body": {"type": "string", "description": "Plain text email body."},
                "cc": {"type": "string", "description": "CC email address(es), comma-separated (optional)."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "search_emails",
        "description": "Search Outlook emails by keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword or phrase."},
                "max_results": {"type": "integer", "description": "Maximum results (default: 10, max: 50).", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_calendar",
        "description": "List upcoming Outlook Calendar events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Maximum events (default: 10, max: 50).", "minimum": 1, "maximum": 50},
                "time_min": {"type": "string", "description": "Start time in ISO 8601 format (e.g. 2026-05-01T00:00:00Z). Defaults to now."},
            },
        },
    },
    {
        "name": "create_event",
        "description": "Create a new Outlook Calendar event.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Event title."},
                "start_datetime": {"type": "string", "description": "Start time in ISO 8601 format, e.g. 2026-05-15T10:00:00."},
                "end_datetime": {"type": "string", "description": "End time in ISO 8601 format."},
                "description": {"type": "string", "description": "Event description (optional)."},
                "location": {"type": "string", "description": "Event location (optional)."},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee email addresses (optional)."},
            },
            "required": ["subject", "start_datetime", "end_datetime"],
        },
    },
    {
        "name": "get_contacts",
        "description": "Search the user's Outlook contacts by name or email.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (name or email fragment)."},
                "max_results": {"type": "integer", "description": "Maximum results (default: 10, max: 25).", "minimum": 1, "maximum": 25},
            },
            "required": ["query"],
        },
    },
]

TOOL_HANDLERS = {
    "read_emails": tool_read_emails,
    "send_email": tool_send_email,
    "search_emails": tool_search_emails,
    "list_calendar": tool_list_calendar,
    "create_event": tool_create_event,
    "get_contacts": tool_get_contacts,
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
                "serverInfo": {"name": "uderia-outlook", "version": "1.0.0"},
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
