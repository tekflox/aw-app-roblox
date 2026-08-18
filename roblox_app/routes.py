"""This app's backend sub-app, mounted by the runtime at
``/api/apps/roblox`` behind the workspace's IdentityGuard.

The two real credentials go to ``ctx.secrets`` via ``POST /settings``,
never through the generic config path (which would land them in plain,
cloud-syncable app config) -- same split as aw-app-google-maps's API key.
Everything else (URLs, ids, the exec-host config that's still an open
question -- see ``mcp/roblox_gui.py``) rides the generic ``config_schema``
path instead, read back off ``ctx.config``.
"""
from __future__ import annotations

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import config, mcp_config
from .mcp import aw_roblox_genie_server, aw_roblox_server

SECRET_KEYS = (config.PILOT_BACKEND_API_KEY, config.ROBLOX_API_KEY)


def build_routes(ctx) -> FastAPI:
    app = FastAPI(title="roblox")

    @app.get("/status")
    async def status() -> dict:
        return {
            "pilot_backend_configured": bool(config.pilot_backend_api_key()),
            "pilot_backend_url": config.pilot_backend_url(),
            "roblox_api_key_configured": bool(config.roblox_api_key()),
            "studio_exec_configured": bool(config.studio_exec_base_url() and config.studio_exec_client_id()),
            "tools": {
                aw_roblox_server.SERVER_NAME: [t["name"] for t in aw_roblox_server.TOOLS_SCHEMA],
                aw_roblox_genie_server.SERVER_NAME: [t["name"] for t in aw_roblox_genie_server.TOOLS_SCHEMA],
            },
        }

    @app.post("/settings")
    async def save_settings(data: dict = Body(...)) -> dict:
        saved = []
        for key in SECRET_KEYS:
            value = (data.get(key) or "").strip()
            if value:
                ctx.secrets.write(key, value)
                saved.append(key)
        if not saved:
            return JSONResponse(
                {"ok": False, "error": f"none of {SECRET_KEYS} were provided"},
                status_code=400,
            )
        return {"ok": True, "saved": saved}

    @app.post("/logout")
    async def clear_secrets(data: dict = Body(default={})) -> dict:
        keys = data.get("keys") or list(SECRET_KEYS)
        for key in keys:
            if key in SECRET_KEYS:
                ctx.secrets.delete(key)
        return {"ok": True, "cleared": keys}

    @app.get("/mcp.json")
    async def mcp_json() -> dict:
        return {"mcpServers": mcp_config.build_mcp_servers()}

    # ------------------------------------------------------------------
    # MCP — Streamable HTTP, TWO separate upstreams, auto-discovered by
    # aw-mcp-gateway's app-scan. Never merge these two routes/servers --
    # see mcp/aw_roblox_genie_server.py's docstring.
    # ------------------------------------------------------------------

    @app.post("/mcp")
    async def mcp_post(request: Request):
        return await _dispatch(request, aw_roblox_server.handle_request)

    @app.get("/mcp")
    async def mcp_get():
        return Response(status_code=405)

    @app.post("/mcp-genie")
    async def mcp_genie_post(request: Request):
        return await _dispatch(request, aw_roblox_genie_server.handle_request)

    @app.get("/mcp-genie")
    async def mcp_genie_get():
        return Response(status_code=405)

    async def _dispatch(request: Request, handler):
        data = await request.json()
        messages = data if isinstance(data, list) else [data]
        responses = []
        for m in messages:
            r = await handler(m)
            if r is not None:
                responses.append(r)
        if not responses:
            return Response(status_code=202)
        return JSONResponse(responses if isinstance(data, list) else responses[0])

    return app
