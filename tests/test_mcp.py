"""The aw-roblox MCP server: tool inventory. Deliberately no network —
every handler that would call out is only checked for its "not
configured" failure path.

The Genie's upstream (aw-roblox-genie) moved to aw-app-roblox-genie
2026-08-26 — its tests (the anti-prompt-injection boundary assertions)
live there now.

Run: python -m pytest tests/test_mcp.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roblox_app import config  # noqa: E402
from roblox_app.mcp import (  # noqa: E402
    aw_roblox_server,
    npc_control,
    roblox_gui,
    self_register,
)


@pytest.fixture(autouse=True)
def _reset_config():
    config.install_resolvers(lambda: {}, lambda name: None)
    yield
    config.install_resolvers(lambda: {}, lambda name: None)


def test_aw_roblox_upstream_carries_all_25_tools():
    names = {t["name"] for t in aw_roblox_server.TOOLS_SCHEMA}
    assert len(names) == 25
    assert names == set(aw_roblox_server._DISPATCH)
    # the two full-power tools the Genie must never get (enforced in
    # aw-app-roblox-genie now, not here)
    assert {"scale_object", "kick_players"} <= names


def test_single_upstream_key():
    servers = self_register.build_mcp_servers(port=9030)
    assert set(servers) == {"aw-roblox"}


def test_npc_control_tool_without_api_key_names_the_missing_config():
    text, is_error = npc_control.DISPATCH["npc_list"]({})
    assert is_error is False  # npc_list itself makes no HTTP call

    text, is_error = npc_control.DISPATCH["list_objects"]({})
    assert is_error is True
    assert config.PILOT_BACKEND_API_KEY in text


def test_roblox_gui_tool_without_exec_config_names_the_missing_config():
    text, is_error = roblox_gui.DISPATCH["roblox_gui_status"]({})
    assert is_error is True
    assert "studio_remote_host_id" in text


def test_config_defaults():
    assert config.pilot_backend_url() == config.DEFAULT_PILOT_BACKEND_URL
    assert config.universe_id() == config.DEFAULT_UNIVERSE_ID
    assert config.default_place_name() == config.DEFAULT_PLACE_NAME
    assert config.studio_remote_host_id() == ""
    assert config.pilot_backend_api_key() == ""


def test_config_resolved_per_call_not_captured_at_import():
    box = {"cfg": {}, "secret": None}
    config.install_resolvers(lambda: box["cfg"], lambda name: box["secret"])
    assert config.pilot_backend_api_key() == ""
    box["secret"] = "sk-later"
    assert config.pilot_backend_api_key() == "sk-later"
    box["cfg"] = {"roblox_universe_id": "999"}
    assert config.universe_id() == "999"
