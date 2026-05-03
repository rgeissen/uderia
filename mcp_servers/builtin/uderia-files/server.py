"""
uderia-files MCP Server

Provides filesystem access tools via stdio transport.
All operations are restricted to admin-configured allowed paths.

Tools:
    read_file     — read a file's content
    write_file    — write (create or overwrite) a file
    list_dir      — list directory contents
    search_files  — search for files by name pattern

Configuration (env vars):
    ALLOWED_PATHS       — comma-separated list of allowed base directories
    MAX_FILE_SIZE_KB    — max file read/write size in KB (default: 512)
"""

import asyncio
import fnmatch
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("uderia-files")

# ── Configuration ──────────────────────────────────────────────────────────────

_raw_paths = os.environ.get("ALLOWED_PATHS", "/tmp/uderia-agent")
ALLOWED_PATHS: list[Path] = [
    Path(p.strip()).resolve()
    for p in _raw_paths.split(",")
    if p.strip()
]
MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_KB", "512")) * 1024

# ── Path safety ────────────────────────────────────────────────────────────────


def _resolve_safe(path_str: str) -> Path | None:
    """Resolve a path and verify it falls under an allowed base."""
    try:
        target = Path(path_str).resolve()
        for base in ALLOWED_PATHS:
            try:
                target.relative_to(base)
                return target
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _check_path(path_str: str) -> tuple[Path | None, str | None]:
    if not path_str:
        return None, "path parameter is required"
    resolved = _resolve_safe(path_str)
    if resolved is None:
        allowed = ", ".join(str(p) for p in ALLOWED_PATHS)
        return None, f"Path '{path_str}' is outside allowed directories: {allowed}"
    return resolved, None


# ── Tool implementations ───────────────────────────────────────────────────────


async def tool_read_file(path: str, encoding: str = "utf-8") -> str:
    resolved, err = _check_path(path)
    if err:
        return json.dumps({"error": err})
    if not resolved.exists():
        return json.dumps({"error": f"File not found: {path}"})
    if not resolved.is_file():
        return json.dumps({"error": f"Not a file: {path}"})
    size = resolved.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        return json.dumps({"error": f"File too large ({size // 1024}KB > {MAX_FILE_SIZE_BYTES // 1024}KB limit)"})
    try:
        content = resolved.read_text(encoding=encoding, errors="replace")
        return json.dumps({
            "path": str(resolved),
            "size_bytes": size,
            "content": content,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_write_file(path: str, content: str, encoding: str = "utf-8") -> str:
    resolved, err = _check_path(path)
    if err:
        return json.dumps({"error": err})
    if len(content.encode(encoding)) > MAX_FILE_SIZE_BYTES:
        return json.dumps({"error": f"Content too large (>{MAX_FILE_SIZE_BYTES // 1024}KB limit)"})
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding=encoding)
        return json.dumps({
            "path": str(resolved),
            "bytes_written": resolved.stat().st_size,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_list_dir(path: str, show_hidden: bool = False) -> str:
    resolved, err = _check_path(path)
    if err:
        return json.dumps({"error": err})
    if not resolved.exists():
        return json.dumps({"error": f"Path not found: {path}"})
    if not resolved.is_dir():
        return json.dumps({"error": f"Not a directory: {path}"})
    try:
        entries = []
        for child in sorted(resolved.iterdir()):
            if not show_hidden and child.name.startswith("."):
                continue
            stat = child.stat()
            entries.append({
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size_bytes": stat.st_size if child.is_file() else None,
            })
        return json.dumps({"path": str(resolved), "entries": entries, "count": len(entries)})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_search_files(
    directory: str,
    pattern: str,
    recursive: bool = True,
    max_results: int = 50,
) -> str:
    resolved, err = _check_path(directory)
    if err:
        return json.dumps({"error": err})
    if not resolved.is_dir():
        return json.dumps({"error": f"Not a directory: {directory}"})
    try:
        matches = []
        if recursive:
            for child in resolved.rglob("*"):
                if fnmatch.fnmatch(child.name, pattern):
                    matches.append(str(child))
                    if len(matches) >= max_results:
                        break
        else:
            for child in resolved.iterdir():
                if fnmatch.fnmatch(child.name, pattern):
                    matches.append(str(child))
                    if len(matches) >= max_results:
                        break
        return json.dumps({
            "directory": str(resolved),
            "pattern": pattern,
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= max_results,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP stdio protocol ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "Read the content of a file. Restricted to admin-configured paths.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path of the file to read."},
                "encoding": {"type": "string", "description": "Text encoding (default: utf-8)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file, creating parent directories as needed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to write."},
                "content": {"type": "string", "description": "Text content to write."},
                "encoding": {"type": "string", "description": "Text encoding (default: utf-8)."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List the contents of a directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list."},
                "show_hidden": {"type": "boolean", "description": "Include hidden files/dirs (default: false)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for files matching a name pattern in a directory tree.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Root directory to search."},
                "pattern": {"type": "string", "description": "Glob pattern for filenames, e.g. '*.csv'."},
                "recursive": {"type": "boolean", "description": "Search subdirectories (default: true)."},
                "max_results": {"type": "integer", "description": "Maximum matches to return (default: 50).", "minimum": 1, "maximum": 200},
            },
            "required": ["directory", "pattern"],
        },
    },
]

TOOL_HANDLERS = {
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_dir": tool_list_dir,
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
                "serverInfo": {"name": "uderia-files", "version": "1.0.0"},
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
