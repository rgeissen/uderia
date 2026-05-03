"""
uderia-google MCP Server

Provides Gmail and Google Calendar tools via stdio transport.
User credentials are passed via environment variables (injected by the platform
from the per-user OAuth token stored in messaging_identities).

Tools:
    read_emails     — list recent emails from inbox
    send_email      — send an email via Gmail
    search_emails   — search emails with a Gmail query string
    list_calendar   — list upcoming calendar events
    create_event    — create a Google Calendar event
    get_contacts    — search Google contacts by name or email

Configuration (env vars injected by platform per-user):
    GOOGLE_ACCESS_TOKEN   — user's OAuth access token
    GOOGLE_REFRESH_TOKEN  — user's OAuth refresh token
    GOOGLE_CLIENT_ID      — admin-configured OAuth client ID
    GOOGLE_CLIENT_SECRET  — admin-configured OAuth client secret

Dependencies:
    google-auth, google-auth-oauthlib, google-api-python-client
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("uderia-google")

ACCESS_TOKEN = os.environ.get("GOOGLE_ACCESS_TOKEN", "")
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _check_credentials() -> str | None:
    if not ACCESS_TOKEN:
        return "Google account not connected. Connect via Platform Components → MCP Servers → uderia-google."
    return None


def _build_gmail():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(
        token=ACCESS_TOKEN,
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _build_calendar():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(
        token=ACCESS_TOKEN,
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


async def tool_read_emails(max_results: int = 10, label: str = "INBOX") -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    try:
        service = _build_gmail()
        result = service.users().messages().list(
            userId="me", labelIds=[label], maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        emails = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            emails.append({
                "id": msg["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": detail.get("snippet", ""),
            })
        return json.dumps({"emails": emails, "count": len(emails)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_send_email(to: str, subject: str, body: str) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import base64
    from email.mime.text import MIMEText
    try:
        service = _build_gmail()
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        result = service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return json.dumps({"sent": True, "message_id": result.get("id")})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_search_emails(query: str, max_results: int = 10) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    try:
        service = _build_gmail()
        result = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        emails = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            emails.append({
                "id": msg["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": detail.get("snippet", ""),
            })
        return json.dumps({"query": query, "emails": emails, "count": len(emails)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_list_calendar(max_results: int = 10, time_min: str = None) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    from datetime import datetime, timezone
    try:
        service = _build_calendar()
        now = time_min or datetime.now(timezone.utc).isoformat()
        result = service.events().list(
            calendarId="primary",
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = []
        for ev in result.get("items", []):
            start = ev.get("start", {})
            end = ev.get("end", {})
            events.append({
                "id": ev.get("id"),
                "summary": ev.get("summary", ""),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "location": ev.get("location", ""),
                "description": ev.get("description", ""),
            })
        return json.dumps({"events": events, "count": len(events)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_create_event(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
    attendees: list[str] = None,
) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    try:
        service = _build_calendar()
        event = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start_datetime},
            "end": {"dateTime": end_datetime},
        }
        if attendees:
            event["attendees"] = [{"email": e} for e in attendees]
        result = service.events().insert(calendarId="primary", body=event).execute()
        return json.dumps({
            "created": True,
            "event_id": result.get("id"),
            "html_link": result.get("htmlLink"),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_get_contacts(query: str, max_results: int = 10) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials(
            token=ACCESS_TOKEN, refresh_token=REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        )
        service = build("people", "v1", credentials=creds, cache_discovery=False)
        result = service.people().searchContacts(
            query=query,
            readMask="names,emailAddresses,phoneNumbers",
            pageSize=max_results,
        ).execute()
        contacts = []
        for result_item in result.get("results", []):
            person = result_item.get("person", {})
            names = person.get("names", [{}])
            emails = person.get("emailAddresses", [])
            phones = person.get("phoneNumbers", [])
            contacts.append({
                "name": names[0].get("displayName", "") if names else "",
                "emails": [e.get("value", "") for e in emails],
                "phones": [p.get("value", "") for p in phones],
            })
        return json.dumps({"query": query, "contacts": contacts, "count": len(contacts)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP stdio protocol ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "read_emails",
        "description": "Read recent emails from the user's Gmail inbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Maximum number of emails (default: 10).", "minimum": 1, "maximum": 50},
                "label": {"type": "string", "description": "Gmail label (default: INBOX)."},
            },
        },
    },
    {
        "name": "send_email",
        "description": "Send an email via the user's Gmail account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Email subject."},
                "body": {"type": "string", "description": "Plain text email body."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "search_emails",
        "description": "Search Gmail using a query string (supports Gmail search syntax: from:, subject:, has:attachment, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query."},
                "max_results": {"type": "integer", "description": "Maximum results (default: 10).", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_calendar",
        "description": "List upcoming Google Calendar events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Maximum events (default: 10).", "minimum": 1, "maximum": 50},
                "time_min": {"type": "string", "description": "Start time in RFC3339 format. Defaults to now."},
            },
        },
    },
    {
        "name": "create_event",
        "description": "Create a new Google Calendar event.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title."},
                "start_datetime": {"type": "string", "description": "Start time in RFC3339 format, e.g. 2026-05-15T10:00:00+02:00."},
                "end_datetime": {"type": "string", "description": "End time in RFC3339 format."},
                "description": {"type": "string", "description": "Event description (optional)."},
                "location": {"type": "string", "description": "Event location (optional)."},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee email addresses (optional)."},
            },
            "required": ["summary", "start_datetime", "end_datetime"],
        },
    },
    {
        "name": "get_contacts",
        "description": "Search the user's Google Contacts by name or email.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (name or email fragment)."},
                "max_results": {"type": "integer", "description": "Maximum results (default: 10).", "minimum": 1, "maximum": 25},
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
                "serverInfo": {"name": "uderia-google", "version": "1.0.0"},
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
