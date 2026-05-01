"""
uderia-web MCP Server

Provides web search and page retrieval tools via stdio transport.

Tools:
    web_search   — search the web using Brave or Serper API
    web_fetch    — fetch the raw HTML/text of a URL
    web_extract  — fetch a URL and extract meaningful text (strips boilerplate)

Configuration (via environment variables set by Uderia admin):
    BRAVE_API_KEY   — Brave Search API key (takes precedence over Serper)
    SERPER_API_KEY  — Serper.dev API key (fallback)
    MAX_RESULTS     — max search results (default: 5)
    FETCH_TIMEOUT_SECONDS — HTTP timeout (default: 15)

Dependencies:
    httpx, beautifulsoup4 (both in Uderia's requirements.txt)
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("uderia-web")

# ── Configuration ─────────────────────────────────────────────────────────────

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "5"))
FETCH_TIMEOUT = int(os.environ.get("FETCH_TIMEOUT_SECONDS", "15"))

# ── Tool implementations ──────────────────────────────────────────────────────


async def _brave_search(query: str, num: int) -> list[dict]:
    """Search via Brave Search API."""
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": num},
            headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("web", {}).get("results", [])[:num]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        return results


async def _serper_search(query: str, num: int) -> list[dict]:
    """Search via Serper.dev API."""
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": num},
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("organic", [])[:num]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results


async def tool_web_search(query: str, num_results: int = None) -> str:
    num = min(int(num_results or MAX_RESULTS), 20)
    if not query:
        return json.dumps({"error": "query parameter is required"})

    try:
        if BRAVE_API_KEY:
            results = await _brave_search(query, num)
        elif SERPER_API_KEY:
            results = await _serper_search(query, num)
        else:
            return json.dumps({"error": "No search API key configured. Set BRAVE_API_KEY or SERPER_API_KEY."})

        return json.dumps({
            "query": query,
            "results": results,
            "count": len(results),
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_web_fetch(url: str, max_chars: int = 8000) -> str:
    if not url:
        return json.dumps({"error": "url parameter is required"})
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Uderia-Web/1.0"})
            resp.raise_for_status()
            text = resp.text[:max_chars]
            return json.dumps({
                "url": str(resp.url),
                "status_code": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "content": text,
                "truncated": len(resp.text) > max_chars,
            }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_web_extract(url: str, max_chars: int = 8000) -> str:
    if not url:
        return json.dumps({"error": "url parameter is required"})
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Uderia-Web/1.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove script, style, nav, footer noise
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            # Collapse blank lines
            lines = [l for l in text.splitlines() if l.strip()]
            cleaned = "\n".join(lines)[:max_chars]
            return json.dumps({
                "url": str(resp.url),
                "title": soup.title.string if soup.title else "",
                "text": cleaned,
                "truncated": len("\n".join(lines)) > max_chars,
            }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP stdio protocol ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": "Search the web and return a list of results with titles, URLs, and snippets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "num_results": {"type": "integer", "description": "Number of results (1-20). Defaults to server config.", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": "Fetch the raw content (HTML or plain text) of a URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch."},
                "max_chars": {"type": "integer", "description": "Maximum characters to return (default 8000).", "minimum": 100},
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_extract",
        "description": "Fetch a URL and extract clean readable text, stripping navigation and boilerplate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to extract text from."},
                "max_chars": {"type": "integer", "description": "Maximum characters to return (default 8000).", "minimum": 100},
            },
            "required": ["url"],
        },
    },
]

TOOL_HANDLERS = {
    "web_search": tool_web_search,
    "web_fetch": tool_web_fetch,
    "web_extract": tool_web_extract,
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
                "serverInfo": {"name": "uderia-web", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": TOOL_DEFINITIONS},
        }

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
        return None  # notification — no response

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
