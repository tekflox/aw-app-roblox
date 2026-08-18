"""The ``aw-roblox`` MCP server — full pilot surface, over Streamable HTTP.

Unifies two of the four monolith servers (``roblox_gui.py`` + 8 tools,
``npc_control.py`` + 17 tools = 25 tools total) behind one upstream, the
same way aw-google-maps serves its tools from this app's own already-
authenticated route instead of a gateway-spawned stdio child (see
``roblox_gui.TOOLS_SCHEMA``'s module docstring — this app's container has
neither the monolith's shared filesystem nor its exec channel, so the
stdio-subprocess shape wouldn't port cleanly anyway).

**Kept deliberately separate from the Genie's upstream**
(:mod:`roblox_app.mcp.aw_roblox_genie_server`) — this is the full-power
surface (``scale_object``, ``kick_players``, GUI automation), reachable
only by whoever this app is configured for (Frederico via any MCP-capable
agent), never by the in-game Genie NPC's own chat-triggered tool calls.
Merging the two into one upstream would erase that boundary — see the
Genie server module's docstring for the actual security rationale.
"""
from __future__ import annotations

import logging

from fastapi.concurrency import run_in_threadpool

from . import npc_control, roblox_gui

log = logging.getLogger("aw_apps.roblox")

SERVER_NAME = "aw-roblox"
SERVER_VERSION = "1.0.0"

TOOLS_SCHEMA = roblox_gui.TOOLS_SCHEMA + npc_control.TOOLS_SCHEMA

_DISPATCH = {**roblox_gui.DISPATCH, **npc_control.DISPATCH}


def _result(req_id, text: str, is_error: bool) -> dict:
    return {"jsonrpc": "2.0", "id": req_id,
            "result": {"content": [{"type": "text", "text": text}],
                       "isError": is_error}}


async def handle_request(request: dict) -> dict | None:
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS_SCHEMA}}
    if method != "tools/call":
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}}

    params = request.get("params") or {}
    name = params.get("name", "")
    args = params.get("arguments") or {}

    handler = _DISPATCH.get(name)
    if not handler:
        return _result(req_id, f"Unknown tool: {name}", True)

    try:
        # Every handler here uses blocking urllib -- must not run on the
        # event loop, a slow backend/exec response would stall every other
        # app route in this process.
        text, is_error = await run_in_threadpool(handler, args)
    except Exception as exc:  # noqa: BLE001 -- last resort, must not 500 the route
        log.exception("aw-roblox MCP tool %s failed", name)
        return _result(req_id, f"{name} failed: {exc}", True)

    return _result(req_id, text, is_error)
