"""Entrypoint referenced by aw-app.json's ``runtime.entrypoint``
("roblox_app.plugin:RobloxAppPlugin").

Same shape as aw-app-google-maps: no subprocess, no venv, no port beyond
this process's own. Both MCP servers are served in-process over HTTP
(see ``mcp_config.py`` / ``routes.py``); ``ctx.config``/``ctx.secrets``
are resolved through callables (:mod:`roblox_app.config`) rather than
read once, so a value saved in Settings takes effect on the very next
tool call with no restart and no gateway reload.
"""
from __future__ import annotations

import logging
import os

from . import config, mcp_config, routes as routes_mod

log = logging.getLogger("aw_apps.roblox")


class RobloxAppPlugin:
    async def activate(self, ctx) -> None:
        self.ctx = ctx

        config.install_resolvers(
            lambda: getattr(ctx, "config", {}) or {},
            lambda name: ctx.secrets.read(name),
        )

        ctx.routes.register(routes_mod.build_routes(ctx))

        port = int(os.environ.get("AW_PORT") or 9030)
        # Rebuilt every boot rather than persisted: the entry embeds this
        # process's hostname, which changes when the workspace container
        # is recreated.
        doc = mcp_config.write_mcp_json(ctx.package_dir, port)

        log.info(
            "aw-app-roblox activated: mcp servers=%s, pilot backend key=%s, "
            "roblox api key=%s, studio exec=%s",
            sorted(doc["mcpServers"]),
            "saved" if config.pilot_backend_api_key() else "NOT SET",
            "saved" if config.roblox_api_key() else "NOT SET",
            "configured" if (config.studio_exec_base_url() and config.studio_exec_client_id()) else "NOT SET (open question, see Kanban card)",
        )

    async def deactivate(self) -> None:
        log.info("aw-app-roblox deactivated")
