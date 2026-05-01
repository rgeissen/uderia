"""
uderia-browser MCP Server

Provides headless browser automation tools via Playwright and stdio transport.

Tools:
    navigate     — navigate to a URL, return page title and URL
    click        — click an element by CSS selector
    fill_form    — fill an input field
    screenshot   — take a screenshot (returns base64 PNG)
    scrape       — navigate and extract page text
    extract_data — extract structured data from a page using a CSS selector

Dependencies:
    playwright (install Chromium with: playwright install chromium)

Configuration (env vars):
    ALLOWED_DOMAINS     — comma-separated domain allowlist; empty = all allowed
    HEADLESS            — "true" (default) or "false"
    PAGE_TIMEOUT_SECONDS — page load timeout (default: 30)
"""

import asyncio
import base64
import json
import logging
import os
import sys
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("uderia-browser")

ALLOWED_DOMAINS_RAW = os.environ.get("ALLOWED_DOMAINS", "")
ALLOWED_DOMAINS: list[str] = [d.strip() for d in ALLOWED_DOMAINS_RAW.split(",") if d.strip()]
HEADLESS = os.environ.get("HEADLESS", "true").lower() != "false"
PAGE_TIMEOUT_MS = int(os.environ.get("PAGE_TIMEOUT_SECONDS", "30")) * 1000

_browser = None
_page = None


def _check_domain(url: str) -> str | None:
    if not ALLOWED_DOMAINS:
        return None  # all allowed
    try:
        host = urlparse(url).hostname or ""
        for domain in ALLOWED_DOMAINS:
            if host == domain or host.endswith(f".{domain}"):
                return None
        return f"Domain '{host}' is not in the allowed domains list: {', '.join(ALLOWED_DOMAINS)}"
    except Exception:
        return f"Invalid URL: {url}"


async def _get_page():
    global _browser, _page
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")

    if _browser is None:
        pw = await async_playwright().__aenter__()
        _browser = await pw.chromium.launch(headless=HEADLESS)
        _page = await _browser.new_page()
        _page.set_default_timeout(PAGE_TIMEOUT_MS)
    return _page


async def tool_navigate(url: str) -> str:
    err = _check_domain(url)
    if err:
        return json.dumps({"error": err})
    try:
        page = await _get_page()
        response = await page.goto(url, wait_until="domcontentloaded")
        return json.dumps({
            "url": page.url,
            "title": await page.title(),
            "status": response.status if response else None,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_click(selector: str) -> str:
    try:
        page = await _get_page()
        await page.click(selector)
        return json.dumps({"clicked": selector, "url": page.url})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_fill_form(selector: str, value: str) -> str:
    try:
        page = await _get_page()
        await page.fill(selector, value)
        return json.dumps({"filled": selector, "value": value})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_screenshot(full_page: bool = False) -> str:
    try:
        page = await _get_page()
        data = await page.screenshot(full_page=full_page)
        b64 = base64.b64encode(data).decode("ascii")
        return json.dumps({"url": page.url, "screenshot_base64": b64, "format": "png"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_scrape(url: str, max_chars: int = 8000) -> str:
    err = _check_domain(url)
    if err:
        return json.dumps({"error": err})
    try:
        page = await _get_page()
        await page.goto(url, wait_until="domcontentloaded")
        text = await page.inner_text("body")
        lines = [l for l in text.splitlines() if l.strip()]
        cleaned = "\n".join(lines)[:max_chars]
        return json.dumps({
            "url": page.url,
            "title": await page.title(),
            "text": cleaned,
            "truncated": len("\n".join(lines)) > max_chars,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_extract_data(selector: str, attribute: str = "innerText") -> str:
    try:
        page = await _get_page()
        elements = await page.query_selector_all(selector)
        results = []
        for el in elements[:50]:
            if attribute == "innerText":
                results.append(await el.inner_text())
            elif attribute == "innerHTML":
                results.append(await el.inner_html())
            else:
                results.append(await el.get_attribute(attribute) or "")
        return json.dumps({
            "selector": selector,
            "attribute": attribute,
            "results": results,
            "count": len(results),
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP stdio protocol ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "navigate",
        "description": "Navigate the browser to a URL and return the page title and final URL.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "The URL to navigate to."}},
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Click an element on the current page using a CSS selector.",
        "inputSchema": {
            "type": "object",
            "properties": {"selector": {"type": "string", "description": "CSS selector of the element to click."}},
            "required": ["selector"],
        },
    },
    {
        "name": "fill_form",
        "description": "Fill an input field on the current page.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of the input field."},
                "value": {"type": "string", "description": "Value to fill."},
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "screenshot",
        "description": "Take a screenshot of the current page. Returns base64-encoded PNG.",
        "inputSchema": {
            "type": "object",
            "properties": {"full_page": {"type": "boolean", "description": "Capture the full scrollable page (default: false)."}},
        },
    },
    {
        "name": "scrape",
        "description": "Navigate to a URL and extract all visible text from the page.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to scrape."},
                "max_chars": {"type": "integer", "description": "Maximum characters to return (default: 8000)."},
            },
            "required": ["url"],
        },
    },
    {
        "name": "extract_data",
        "description": "Extract data from the current page using a CSS selector.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector to match elements."},
                "attribute": {"type": "string", "description": "Attribute to extract: 'innerText', 'innerHTML', or any HTML attribute name (default: innerText)."},
            },
            "required": ["selector"],
        },
    },
]

TOOL_HANDLERS = {
    "navigate": tool_navigate,
    "click": tool_click,
    "fill_form": tool_fill_form,
    "screenshot": tool_screenshot,
    "scrape": tool_scrape,
    "extract_data": tool_extract_data,
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
                "serverInfo": {"name": "uderia-browser", "version": "1.0.0"},
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
