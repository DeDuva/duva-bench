"""The tool server an arm's toolset is actually served by.

`materialize()` writes a toolset definition into a task and declares this module
as an MCP server in the task's ``task.toml``. Harbor passes that declaration to
the agent, and an MCP-registering agent turns it into callable tools under
whatever names the arm chose. That is the whole of the toolset manipulation, and
until 2026-08-10 it did not exist: the definition was written to
``duva/toolset.json`` and nothing read it.

**Capabilities, not names.** Every tool in a definition carries a ``capability``
naming the implementation it is served by, and this module holds the
implementations. Two arms of a familiarity study serve the *same* capabilities
under *different* names, which is what makes them isomorphic.

**Why the capability ids are what they are.** They name implementations —
`fs.read`, `proc.run` — and deliberately not the tool names any study uses. A
twin arm's container must not contain the vocabulary that arm is being tested
without; an agent with a shell can read every file in its own task, so a single
example of a standard tool name written down here would hand it the answer. That
is not hypothetical: the first version of this docstring contained one, and
`tests/test_arms.py` caught it by scanning a materialized twin for the words it
must not contain.

The ids do leak the *kind* of each tool, which the tool's own description already
leaks by design (`arms/docs.py` varies documentation; this module does not).

**This file is copied into the container verbatim.** Nothing in it — comment,
docstring or identifier — may name a tool from any study's vocabulary. Runs over
stdio with no dependencies beyond the standard library, because it has to work in
whatever image the task brought.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2024-11-05"

#: Where `materialize()` puts the definition inside the task.
DEFINITION_ENV = "DUVA_TOOLSET"

#: How long any single `proc.run` may take. A tool that can hang forever turns a
#: trial's step budget into a wall-clock lottery.
COMMAND_TIMEOUT_SECONDS = 120


class CapabilityError(RuntimeError):
    """A definition named a capability this server does not implement."""


def _read(arguments: dict[str, Any]) -> str:
    path = Path(str(arguments["path"]))
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = max(1, int(arguments.get("start_line") or 1))
    limit = arguments.get("max_lines")
    end = start - 1 + int(limit) if limit else len(lines)
    return "\n".join(lines[start - 1 : end])


def _write(arguments: dict[str, Any]) -> str:
    path = Path(str(arguments["path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    content = str(arguments.get("content", ""))
    path.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {path}"


def _list(arguments: dict[str, Any]) -> str:
    path = Path(str(arguments.get("path") or "."))
    if not path.is_dir():
        return f"{path} is not a directory"
    return "\n".join(sorted(entry.name for entry in path.iterdir()))


def _run(arguments: dict[str, Any]) -> str:
    completed = subprocess.run(
        str(arguments["command"]),
        shell=True,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        cwd=str(arguments.get("cwd") or os.getcwd()),
    )
    return json.dumps(
        {
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-8000:],
            "stderr": completed.stderr[-8000:],
        }
    )


CAPABILITIES = {
    "fs.read": _read,
    "fs.write": _write,
    "fs.list": _list,
    "proc.run": _run,
}


def load_definition() -> dict[str, Any]:
    path = os.environ.get(DEFINITION_ENV)
    if not path:
        raise CapabilityError(f"{DEFINITION_ENV} is not set; nothing to serve")
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise CapabilityError(f"{path} does not hold a toolset definition object")
    return loaded


def _tool_schemas(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """The `tools/list` payload: exactly what the arm's definition says."""
    return [
        {
            "name": str(tool["name"]),
            "description": str(tool.get("description") or ""),
            "inputSchema": tool.get("parameters")
            or {"type": "object", "properties": {}, "required": []},
        }
        for tool in definition.get("tools", [])
        if tool.get("name")
    ]


def _dispatch(definition: dict[str, Any], name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    for tool in definition.get("tools", []):
        if tool.get("name") != name:
            continue
        capability = str(tool.get("capability") or "")
        handler = CAPABILITIES.get(capability)
        if handler is None:
            return _error(
                f"tool {name!r} names capability {capability!r}, which is not implemented"
            )
        # A twin renames parameters as well as tools, so the served argument
        # names are mapped back to the roles the implementation expects. The
        # roles are generic (`path`, `command`) and leak no more than the tool's
        # own description does.
        roles = tool.get("parameter_roles") or {}
        mapped = {str(roles.get(key, key)): value for key, value in arguments.items()}
        try:
            return {"content": [{"type": "text", "text": handler(mapped)}]}
        except Exception as failure:  # a tool that raises is a tool result, not a crash
            return _error(f"{name} failed: {failure}")
    return _error(f"no such tool: {name}")


def _error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def handle(definition: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": str(definition.get("name") or "duva-toolset"),
                    "version": "1.0.0",
                },
            },
        }
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tool_schemas(definition)}}
    if method == "tools/call":
        params = message.get("params") or {}
        result = _dispatch(definition, str(params.get("name")), params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if request_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> int:
    definition = load_definition()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(definition, message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
