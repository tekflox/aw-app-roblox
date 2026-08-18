"""Builds this app's own root ``mcp.json`` — the file aw-mcp-gateway's
app-scan reads directly.

``contributes.mcp.provides`` in aw-app.json registers **nothing**; it is
the marketplace's "what you get" list (see aw-app-google-maps's
``mcp_config.py`` for the same note). Written unconditionally on every
activate, whether or not any config/secret is set yet -- both servers
degrade *usefully* without configuration (a clear "not configured"
message per tool), which is a better failure than the tools not existing
at all.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .mcp import self_register


def build_mcp_servers(port: int | None = None) -> dict:
    return self_register.build_mcp_servers(port)


def write_mcp_json(package_dir: str, port: int | None = None) -> dict:
    """Regenerate ``<package_dir>/mcp.json``, skipping the write when
    nothing changed.

    The skip matters: aw-mcp-gateway reloads on **mtime**, and each
    reload briefly drops every tool it proxies -- including those of the
    session that triggered it. An unconditional rewrite on every activate
    is a reload loop.
    """
    doc = {"mcpServers": build_mcp_servers(port or int(os.environ.get("AW_PORT") or 9030))}
    body = json.dumps(doc, indent=2) + "\n"
    path = Path(package_dir) / "mcp.json"
    try:
        if path.read_text(encoding="utf-8") == body:
            return doc
    except FileNotFoundError:
        pass
    path.write_text(body, encoding="utf-8")
    return doc
