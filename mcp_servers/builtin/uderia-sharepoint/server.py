"""
uderia-sharepoint MCP Server

Provides Microsoft SharePoint and OneDrive tools via stdio transport.
User credentials are passed via environment variables (injected by the platform
from the per-user OAuth token stored in messaging_identities).

Tools:
    list_sites      — list SharePoint sites the user has access to
    list_libraries  — list document libraries in a SharePoint site
    list_files      — list files and folders in a library or folder
    read_file       — get file metadata and content (text files, max 4 MB)
    upload_file     — create or update a file in a library
    search_files    — search across all SharePoint/OneDrive content

Configuration (env vars injected by platform per-user):
    MS_SHAREPOINT_ACCESS_TOKEN   — user's OAuth access token
    MS_SHAREPOINT_REFRESH_TOKEN  — user's OAuth refresh token

Dependencies:
    httpx
"""

import asyncio
import base64
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("uderia-sharepoint")

ACCESS_TOKEN = os.environ.get("MS_SHAREPOINT_ACCESS_TOKEN", "")
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MAX_TEXT_BYTES = 4 * 1024 * 1024  # 4 MB


def _check_credentials() -> str | None:
    if not ACCESS_TOKEN:
        return "Microsoft account not connected. Connect via Platform Components → Connectors → uderia-sharepoint."
    return None


def _headers() -> dict:
    return {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}


async def tool_list_sites(max_results: int = 20) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/sites?search=*",
                headers=_headers(),
                params={"$top": min(max_results, 100), "$select": "id,displayName,webUrl,description"},
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        sites = [
            {
                "id": s.get("id"),
                "name": s.get("displayName", ""),
                "url": s.get("webUrl", ""),
                "description": s.get("description", ""),
            }
            for s in data.get("value", [])
        ]
        return json.dumps({"sites": sites, "count": len(sites)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_list_libraries(site_id: str) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_GRAPH_BASE}/sites/{site_id}/drives",
                headers=_headers(),
                params={"$select": "id,name,driveType,webUrl"},
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        libraries = [
            {
                "id": d.get("id"),
                "name": d.get("name", ""),
                "type": d.get("driveType", ""),
                "url": d.get("webUrl", ""),
            }
            for d in data.get("value", [])
        ]
        return json.dumps({"site_id": site_id, "libraries": libraries, "count": len(libraries)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_list_files(drive_id: str, folder_path: str = "/", max_results: int = 50) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        clean_path = folder_path.strip("/")
        if clean_path:
            url = f"{_GRAPH_BASE}/drives/{drive_id}/root:/{clean_path}:/children"
        else:
            url = f"{_GRAPH_BASE}/drives/{drive_id}/root/children"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url, headers=_headers(),
                params={"$top": min(max_results, 200), "$select": "id,name,size,lastModifiedDateTime,file,folder,webUrl"},
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        items = []
        for item in data.get("value", []):
            items.append({
                "id": item.get("id"),
                "name": item.get("name", ""),
                "type": "folder" if "folder" in item else "file",
                "size": item.get("size"),
                "modified": item.get("lastModifiedDateTime", ""),
                "url": item.get("webUrl", ""),
                "mime_type": item.get("file", {}).get("mimeType", "") if "file" in item else "",
            })
        return json.dumps({"drive_id": drive_id, "folder": folder_path, "items": items, "count": len(items)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_read_file(drive_id: str, item_id: str) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            meta_resp = await client.get(
                f"{_GRAPH_BASE}/drives/{drive_id}/items/{item_id}",
                headers=_headers(),
                params={"$select": "id,name,size,file,webUrl,lastModifiedDateTime"},
            )
        if meta_resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {meta_resp.status_code}: {meta_resp.text}"})
        meta = meta_resp.json()
        file_info = meta.get("file", {})
        size = meta.get("size", 0)
        mime = file_info.get("mimeType", "")

        text_mimes = {"text/", "application/json", "application/xml", "application/javascript", "application/typescript"}
        is_text = size <= _MAX_TEXT_BYTES and (any(mime.startswith(m) for m in text_mimes) or mime == "")

        content = None
        if is_text:
            async with httpx.AsyncClient(timeout=30.0) as client:
                dl_resp = await client.get(
                    f"{_GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content",
                    headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                    follow_redirects=True,
                )
            if dl_resp.status_code == 200:
                try:
                    content = dl_resp.content.decode("utf-8", errors="replace")
                except Exception:
                    content = None

        return json.dumps({
            "id": meta.get("id"),
            "name": meta.get("name", ""),
            "size": size,
            "mime_type": mime,
            "modified": meta.get("lastModifiedDateTime", ""),
            "url": meta.get("webUrl", ""),
            "content": content,
            "content_truncated": len(content) > 10000 if content else False,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_upload_file(drive_id: str, folder_path: str, file_name: str, content: str) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        clean_path = folder_path.strip("/")
        if clean_path:
            url = f"{_GRAPH_BASE}/drives/{drive_id}/root:/{clean_path}/{file_name}:/content"
        else:
            url = f"{_GRAPH_BASE}/drives/{drive_id}/root:/{file_name}:/content"
        encoded = content.encode("utf-8")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                url,
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "text/plain"},
                content=encoded,
            )
        if resp.status_code not in (200, 201):
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        result = resp.json()
        return json.dumps({
            "uploaded": True,
            "id": result.get("id"),
            "name": result.get("name"),
            "size": result.get("size"),
            "url": result.get("webUrl", ""),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_search_files(query: str, max_results: int = 20) -> str:
    err = _check_credentials()
    if err:
        return json.dumps({"error": err})
    import httpx
    try:
        payload = {
            "requests": [{
                "entityTypes": ["driveItem"],
                "query": {"queryString": query},
                "fields": ["id", "name", "webUrl", "lastModifiedDateTime", "size", "parentReference"],
                "size": min(max_results, 50),
            }]
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_GRAPH_BASE}/search/query",
                headers=_headers(),
                json=payload,
            )
        if resp.status_code != 200:
            return json.dumps({"error": f"Graph API error {resp.status_code}: {resp.text}"})
        data = resp.json()
        hits = []
        for response in data.get("value", []):
            for hit_container in response.get("hitsContainers", []):
                for hit in hit_container.get("hits", []):
                    resource = hit.get("resource", {})
                    hits.append({
                        "id": resource.get("id"),
                        "name": resource.get("name", ""),
                        "url": resource.get("webUrl", ""),
                        "modified": resource.get("lastModifiedDateTime", ""),
                        "size": resource.get("size"),
                        "site": resource.get("parentReference", {}).get("siteId", ""),
                        "drive_id": resource.get("parentReference", {}).get("driveId", ""),
                        "score": hit.get("rank"),
                    })
        return json.dumps({"query": query, "results": hits, "count": len(hits)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP stdio protocol ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "list_sites",
        "description": "List SharePoint sites the user has access to.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Maximum number of sites (default: 20, max: 100).", "minimum": 1, "maximum": 100},
            },
        },
    },
    {
        "name": "list_libraries",
        "description": "List document libraries (drives) in a SharePoint site.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "SharePoint site ID (from list_sites)."},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and folders in a SharePoint document library or subfolder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "drive_id": {"type": "string", "description": "Drive/library ID (from list_libraries)."},
                "folder_path": {"type": "string", "description": "Folder path relative to library root (default: '/', the root)."},
                "max_results": {"type": "integer", "description": "Maximum items (default: 50, max: 200).", "minimum": 1, "maximum": 200},
            },
            "required": ["drive_id"],
        },
    },
    {
        "name": "read_file",
        "description": "Get file metadata and content (text files up to 4 MB). Returns content as a string for text files; metadata only for binary files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "drive_id": {"type": "string", "description": "Drive/library ID."},
                "item_id": {"type": "string", "description": "File item ID (from list_files)."},
            },
            "required": ["drive_id", "item_id"],
        },
    },
    {
        "name": "upload_file",
        "description": "Create or update a text file in a SharePoint document library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "drive_id": {"type": "string", "description": "Drive/library ID."},
                "folder_path": {"type": "string", "description": "Target folder path (use '/' for root)."},
                "file_name": {"type": "string", "description": "File name including extension (e.g. report.txt)."},
                "content": {"type": "string", "description": "Text content to write to the file."},
            },
            "required": ["drive_id", "folder_path", "file_name", "content"],
        },
    },
    {
        "name": "search_files",
        "description": "Search across all SharePoint sites and OneDrive for files matching a query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (file name, content keywords, etc.)."},
                "max_results": {"type": "integer", "description": "Maximum results (default: 20, max: 50).", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    },
]

TOOL_HANDLERS = {
    "list_sites": tool_list_sites,
    "list_libraries": tool_list_libraries,
    "list_files": tool_list_files,
    "read_file": tool_read_file,
    "upload_file": tool_upload_file,
    "search_files": tool_search_files,
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
                "serverInfo": {"name": "uderia-sharepoint", "version": "1.0.0"},
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
