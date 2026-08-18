"""Entries describing this app's own two ``/mcp`` endpoints, for
aw-mcp-gateway's app-scan (``scan_app_mcp_servers()``, which reads
``<app dir>/mcp.json``).

TWO entries, not one -- ``aw-roblox`` (full surface) and
``aw-roblox-genie`` (the Genie's narrow subset) each get their own
gateway upstream key and their own route, so a caller wired only to one
profile can never reach the other's tools regardless of misconfiguration
elsewhere. See ``aw_roblox_server.py``'s and ``aw_roblox_genie_server.py``'s
module docstrings for why that boundary has to live at this level.

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

GENIE_SERVER_NAME = "aw-roblox-genie"
GENIE_ROUTE_PATH = "/api/apps/roblox/mcp-genie"


def _entry(route_path: str, port: int | None) -> dict:
    host = socket.gethostname()
    port = port or int(os.environ.get("AW_PORT") or 9030)
    entry: dict = {
        "type": "http",
        "url": f"http://{host}:{port}{route_path}",
        "enabled": True,
    }
    api_key = os.environ.get("AW_WORKSPACE_API_KEY")
    if api_key:
        entry["headers"] = {"X-Api-Key": api_key}
    return entry


def build_mcp_servers(port: int | None = None) -> dict:
    return {
        ROBLOX_SERVER_NAME: _entry(ROBLOX_ROUTE_PATH, port),
        GENIE_SERVER_NAME: _entry(GENIE_ROUTE_PATH, port),
    }
