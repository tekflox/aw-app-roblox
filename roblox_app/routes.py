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

from . import config, mcp_config, remote_host_client
from .mcp import aw_roblox_server, roblox_gui

SECRET_KEYS = (config.PILOT_BACKEND_API_KEY, config.ROBLOX_API_KEY)

# What roblox_gui's _WINDOWS_SCRIPT needs on the exec host's `python` --
# pywinauto (UI Automation), Pillow (roblox_gui_screenshot's ImageGrab),
# pywin32 (pywinauto's backend dependency on Windows).
_STUDIO_DEPS = ("pywinauto", "pillow", "pywin32")


def build_routes(ctx) -> FastAPI:
    app = FastAPI(title="roblox")

    @app.get("/status")
    async def status() -> dict:
        return {
            "pilot_backend_configured": bool(config.pilot_backend_api_key()),
            "pilot_backend_url": config.pilot_backend_url(),
            "roblox_api_key_configured": bool(config.roblox_api_key()),
            "studio_remote_host_id": config.studio_remote_host_id(),
            "studio_exec_configured": bool(config.studio_remote_host_id()),
            "logged_in": bool(config.studio_remote_host_id()),
            "tools": {
                aw_roblox_server.SERVER_NAME: [t["name"] for t in aw_roblox_server.TOOLS_SCHEMA],
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

    @app.get("/remote-hosts")
    async def remote_hosts() -> dict:
        """Hosts this account has linked via aw-remote-hosts, for picking a
        value for the studio_remote_host_id config field — config_schema has
        no dynamic-dropdown mechanism, so this is the "browse the options"
        step a human (or agent) does before pasting an id into Settings."""
        client = remote_host_client.RemoteHostClient()
        if not client.configured:
            return {"configured": False, "hosts": [], "current": config.studio_remote_host_id()}
        try:
            data = client.list_account_hosts()
        except remote_host_client.RemoteHostError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return {"configured": True, "hosts": data.get("hosts") or [], "current": config.studio_remote_host_id()}

    @app.post("/provision")
    async def provision() -> dict:
        """Installs what roblox_gui's Windows-side script needs (pywinauto,
        Pillow, pywin32) on studio_remote_host_id via pip --user. Idempotent
        -- pip no-ops on an already-satisfied requirement -- so this is safe
        to press again after an app update or a host reimage."""
        host_ref = config.studio_remote_host_id()
        if not host_ref:
            return JSONResponse({"ok": False, "error": "studio_remote_host_id is not set"}, status_code=400)
        client = remote_host_client.RemoteHostClient()
        try:
            host_id = remote_host_client.resolve_host_ref(client, host_ref)
            command = "python -m pip install --user " + " ".join(_STUDIO_DEPS)
            stdout, stderr, returncode = client.run(command, host_id, timeout_s=180)
        except remote_host_client.RemoteHostError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
        return {
            "ok": returncode == 0,
            "host_id": host_id,
            "returncode": returncode,
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
        }

    @app.post("/test")
    async def test_studio_connection() -> dict:
        """Round-trips roblox_gui_status against studio_remote_host_id --
        the same call an agent's roblox_gui_status MCP tool makes, exposed
        here so a human can verify the wiring from the app's own window
        without going through an agent."""
        return roblox_gui.status()

    @app.get("/mcp.json")
    async def mcp_json() -> dict:
        return {"mcpServers": mcp_config.build_mcp_servers()}

    # ------------------------------------------------------------------
    # MCP — Streamable HTTP, auto-discovered by aw-mcp-gateway's app-scan.
    # ------------------------------------------------------------------

    @app.post("/mcp")
    async def mcp_post(request: Request):
        return await _dispatch(request, aw_roblox_server.handle_request)

    @app.get("/mcp")
    async def mcp_get():
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
