"""The ``aw-roblox-genie`` MCP server — the in-game Genie NPC's narrow surface.

Unifies the other two monolith servers (``genie_kanban.py`` + 2 tools,
``genie_npc_control.py`` + 14 tools = 16 tools total) behind a SEPARATE
upstream from :mod:`roblox_app.mcp.aw_roblox_server`. This split is the
whole point of this app existing as two upstreams instead of one merged
MCP -- see that module's docstring, and the Kanban card that requested
this port, for the anti-prompt-injection rationale: the Genie is talked
to by any random player, so it must never be able to reach
``scale_object``/``kick_players`` (npc-control) or anything outside
``source=roblox-genie`` cards (genie-kanban), regardless of gateway
profile misconfiguration -- which only holds if those tools never exist
on this process's side of the wire in the first place, not just behind
an access-control list.

``list_objects``/``npc_list`` are the two tools this server shares a
NAME with in :mod:`roblox_app.mcp.aw_roblox_server` -- harmless here
since each is served under its own upstream prefix by the gateway
(``aw__aw_roblox__list_objects`` vs ``aw__aw_roblox_genie__list_objects``),
never merged into one namespace.
"""
from __future__ import annotations

import logging

from fastapi.concurrency import run_in_threadpool

from . import genie_kanban, genie_npc_control

log = logging.getLogger("aw_apps.roblox_genie")

SERVER_NAME = "aw-roblox-genie"
SERVER_VERSION = "1.0.0"

TOOLS_SCHEMA = genie_kanban.TOOLS_SCHEMA + genie_npc_control.TOOLS_SCHEMA

_DISPATCH = {**genie_kanban.DISPATCH, **genie_npc_control.DISPATCH}

assert not {"scale_object", "kick_players", "set_lighting"} & set(_DISPATCH), (
    "aw-roblox-genie must never carry scale_object/kick_players/set_lighting -- anti-prompt-injection boundary"
)


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
        text, is_error = await run_in_threadpool(handler, args)
    except Exception as exc:  # noqa: BLE001 -- last resort, must not 500 the route
        log.exception("aw-roblox-genie MCP tool %s failed", name)
        return _result(req_id, f"{name} failed: {exc}", True)

    return _result(req_id, text, is_error)
