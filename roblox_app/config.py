"""Config/secret resolvers shared by both MCP upstreams.

Two different stores, same split aw-google-maps and aw-app-notion use:

* Plain, non-sensitive knobs (URLs, ids, default place name) ride the
  generic ``config_schema`` path (``ctx.config``, editable via the
  Settings gear since ``config_visible`` defaults true).
* The two real credentials (the roblox-pilot-backend API key, and the
  Roblox Open Cloud key ``force_shutdown_servers`` needs) go to
  ``ctx.secrets`` instead, via this app's own ``POST /settings`` route —
  never through the generic config path, which would land them in plain,
  cloud-syncable app config.

Resolved through callables, not read once at ``activate()`` time: a value
saved in Settings must take effect on the very next tool call, no restart.
"""
from __future__ import annotations

from typing import Callable

_config: Callable[[], dict] = lambda: {}
_secret: Callable[[str], str | None] = lambda name: None

DEFAULT_PILOT_BACKEND_URL = "https://roblox-pilot-backend.app.aw.tekflox.com"
DEFAULT_UNIVERSE_ID = "2019066227"
DEFAULT_PLACE_NAME = "fredericowu's Place"

PILOT_BACKEND_API_KEY = "roblox_pilot_backend_api_key"
ROBLOX_API_KEY = "roblox_api_key"


def install_resolvers(config_fn: Callable[[], dict], secret_fn: Callable[[str], str | None]) -> None:
    """Called once from ``plugin.activate()``."""
    global _config, _secret
    _config = config_fn
    _secret = secret_fn


def _cfg() -> dict:
    try:
        return _config() or {}
    except Exception:
        return {}


def pilot_backend_url() -> str:
    return (_cfg().get("roblox_pilot_backend_url") or DEFAULT_PILOT_BACKEND_URL).rstrip("/")


def pilot_backend_api_key() -> str:
    return (_secret(PILOT_BACKEND_API_KEY) or "").strip()


def universe_id() -> str:
    return str(_cfg().get("roblox_universe_id") or DEFAULT_UNIVERSE_ID)


def roblox_api_key() -> str:
    return (_secret(ROBLOX_API_KEY) or "").strip()


def default_place_name() -> str:
    return _cfg().get("roblox_place_name") or DEFAULT_PLACE_NAME


def studio_exec_base_url() -> str:
    """Base URL of an HTTP endpoint implementing the same NDJSON exec
    contract the monolith's agents-platform ``/api/clients/{id}/exec``
    used — see ``mcp/roblox_gui.py``'s module docstring for the exact
    shape and why this is left unconfigured by default (open question,
    same as the aw-app-android-studio card)."""
    return (_cfg().get("studio_exec_base_url") or "").rstrip("/")


def studio_exec_client_id() -> str:
    return _cfg().get("studio_exec_client_id") or ""
