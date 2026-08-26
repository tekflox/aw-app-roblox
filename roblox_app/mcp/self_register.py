"""Entry describing this app's own ``/mcp`` endpoint, for aw-mcp-gateway's
app-scan (``scan_app_mcp_servers()``, which reads ``<app dir>/mcp.json``).

Used to also register a second ``aw-roblox-genie`` upstream here -- that
server (the Genie NPC's narrow, chat-injection-safe subset) moved to its
own app, ``aw-app-roblox-genie``, 2026-08-26, so a random player's chat
message never shares a package/permission boundary with this app's full
pilot surface. See that app's README for the security rationale.

Tier-1 (in-process): this *is* the aw-workspace process, so
``socket.gethostname()`` is exactly the value ContainerSupervisor injects
into sibling containers as ``AW_WORKSPACE_HOST``, and
``AW_WORKSPACE_API_KEY`` is already in this process's environment --
nothing has to be provisioned. The header is required because Tier-1
routes sit behind IdentityGuard.
"""
from __future__ import annotations

import os
import socket

ROBLOX_SERVER_NAME = "aw-roblox"
ROBLOX_ROUTE_PATH = "/api/apps/roblox/mcp"


def build_mcp_servers(port: int | None = None) -> dict:
    host = socket.gethostname()
    port = port or int(os.environ.get("AW_PORT") or 9030)
    entry: dict = {
        "type": "http",
        "url": f"http://{host}:{port}{ROBLOX_ROUTE_PATH}",
        "enabled": True,
    }
    api_key = os.environ.get("AW_WORKSPACE_API_KEY")
    if api_key:
        entry["headers"] = {"X-Api-Key": api_key}
    return {ROBLOX_SERVER_NAME: entry}
