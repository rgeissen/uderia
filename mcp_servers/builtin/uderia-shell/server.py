"""
uderia-shell MCP Server

Executes commands inside a per-invocation Docker container.
Every call spawns a fresh throwaway container, executes the command,
captures stdout/stderr, then destroys the container.

Security model:
    - Admin governance layer (who can access): controlled by platform MCP governance settings
    - Docker isolation layer (what commands can touch): fresh container per invocation,
      no host filesystem access by default, no outbound network by default

All invocations are audit-logged. Docker must be available on the host.

Tools:
    exec_command    — run a single shell command in a container
    run_script      — run a multi-line Python or shell script in a container
    list_processes  — list running processes in a container (via Docker stats)
    kill_process    — kill a named process (by sending SIGKILL to PID in a container)

Configuration (env vars):
    DOCKER_IMAGE                — container image (default: python:3.11-slim)
    ALLOWED_COMMANDS            — comma-separated command prefix allowlist
    MOUNT_PATHS                 — host:container mount specs (comma-separated)
    EXECUTION_TIMEOUT_SECONDS   — max execution time per command (default: 30)
    MEMORY_LIMIT_MB             — container memory limit in MB (default: 512)
"""

import asyncio
import json
import logging
import os
import shlex
import sys
from typing import Any

logger = logging.getLogger("uderia-shell")

DOCKER_IMAGE = os.environ.get("DOCKER_IMAGE", "python:3.11-slim")
_raw_cmds = os.environ.get("ALLOWED_COMMANDS", "python,pip,ls,cat,grep,find,echo,date,pwd,env")
ALLOWED_COMMANDS: list[str] = [c.strip() for c in _raw_cmds.split(",") if c.strip()]
_raw_mounts = os.environ.get("MOUNT_PATHS", "")
MOUNT_PATHS: list[str] = [m.strip() for m in _raw_mounts.split(",") if m.strip()]
EXECUTION_TIMEOUT = int(os.environ.get("EXECUTION_TIMEOUT_SECONDS", "30"))
MEMORY_LIMIT_MB = int(os.environ.get("MEMORY_LIMIT_MB", "512"))


# ── Docker availability check ──────────────────────────────────────────────────

async def _check_docker() -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=5)
        if proc.returncode != 0:
            return "Docker is not running or not accessible."
        return None
    except FileNotFoundError:
        return "Docker is not installed on this host."
    except asyncio.TimeoutError:
        return "Docker info timed out."


def _check_allowed(command: str) -> str | None:
    if not ALLOWED_COMMANDS:
        return None  # empty = any command allowed
    cmd_name = shlex.split(command)[0] if command.strip() else ""
    for allowed in ALLOWED_COMMANDS:
        if cmd_name == allowed or cmd_name.startswith(allowed + " "):
            return None
    return (
        f"Command '{cmd_name}' is not in the allowed list: {', '.join(ALLOWED_COMMANDS)}. "
        "Ask your administrator to update the ALLOWED_COMMANDS configuration."
    )


def _build_docker_args(interactive: bool = False) -> list[str]:
    args = [
        "docker", "run", "--rm",
        "--network=none",
        f"--memory={MEMORY_LIMIT_MB}m",
        "--cpus=1",
        "--user=nobody",
        "--read-only",
        "--tmpfs=/tmp:rw,size=50m",
    ]
    for mount in MOUNT_PATHS:
        args.extend(["-v", mount])
    if interactive:
        args.extend(["-i"])
    args.append(DOCKER_IMAGE)
    return args


# ── Tool implementations ───────────────────────────────────────────────────────

async def tool_exec_command(command: str) -> str:
    docker_err = await _check_docker()
    if docker_err:
        return json.dumps({"error": docker_err})

    allow_err = _check_allowed(command)
    if allow_err:
        return json.dumps({"error": allow_err})

    docker_args = _build_docker_args() + ["sh", "-c", command]
    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=EXECUTION_TIMEOUT
        )
        return json.dumps({
            "command": command,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:4096],
            "stderr": stderr.decode("utf-8", errors="replace")[:2048],
        }, ensure_ascii=False)
    except asyncio.TimeoutError:
        return json.dumps({"error": f"Command timed out after {EXECUTION_TIMEOUT}s", "command": command})
    except Exception as exc:
        return json.dumps({"error": str(exc), "command": command})


async def tool_run_script(script: str, language: str = "python") -> str:
    docker_err = await _check_docker()
    if docker_err:
        return json.dumps({"error": docker_err})

    if language == "python":
        interpreter = ["python3", "-c", script]
    elif language in ("sh", "bash", "shell"):
        interpreter = ["sh", "-c", script]
    else:
        return json.dumps({"error": f"Unsupported language: {language}. Use 'python' or 'sh'."})

    docker_args = _build_docker_args() + interpreter
    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=EXECUTION_TIMEOUT
        )
        return json.dumps({
            "language": language,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:8192],
            "stderr": stderr.decode("utf-8", errors="replace")[:2048],
        }, ensure_ascii=False)
    except asyncio.TimeoutError:
        return json.dumps({"error": f"Script timed out after {EXECUTION_TIMEOUT}s"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_list_processes() -> str:
    docker_err = await _check_docker()
    if docker_err:
        return json.dumps({"error": docker_err})
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        lines = stdout.decode().strip().splitlines()
        containers = []
        for line in lines:
            parts = line.split("\t")
            if len(parts) == 4:
                containers.append({"id": parts[0], "image": parts[1], "status": parts[2], "name": parts[3]})
        return json.dumps({"containers": containers, "count": len(containers)})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_kill_process(container_id: str) -> str:
    docker_err = await _check_docker()
    if docker_err:
        return json.dumps({"error": docker_err})
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "kill", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return json.dumps({"killed": container_id})
        return json.dumps({"error": stderr.decode("utf-8", errors="replace"), "container_id": container_id})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── MCP stdio protocol ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "exec_command",
        "description": "Execute a shell command in a fresh Docker container. The container is destroyed after execution. No host filesystem or network access.",
        "inputSchema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The shell command to run."}},
            "required": ["command"],
        },
    },
    {
        "name": "run_script",
        "description": "Run a Python or shell script in a fresh Docker container.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "The script content to execute."},
                "language": {"type": "string", "description": "'python' or 'sh' (default: python)."},
            },
            "required": ["script"],
        },
    },
    {
        "name": "list_processes",
        "description": "List currently running Docker containers on the host.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kill_process",
        "description": "Kill a running Docker container by container ID or name.",
        "inputSchema": {
            "type": "object",
            "properties": {"container_id": {"type": "string", "description": "Docker container ID or name."}},
            "required": ["container_id"],
        },
    },
]

TOOL_HANDLERS = {
    "exec_command": tool_exec_command,
    "run_script": tool_run_script,
    "list_processes": tool_list_processes,
    "kill_process": tool_kill_process,
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
                "serverInfo": {"name": "uderia-shell", "version": "1.0.0"},
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
