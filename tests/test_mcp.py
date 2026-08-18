"""The two MCP servers this app ships: tool inventory and, above all, the
anti-prompt-injection boundary between them (scale_object/kick_players
must never reach the Genie's upstream). Deliberately no network — every
handler that would call out is only checked for its "not configured"
failure path.

Run: python -m pytest tests/test_mcp.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roblox_app import config  # noqa: E402
from roblox_app.mcp import (  # noqa: E402
    aw_roblox_genie_server,
    aw_roblox_server,
    genie_kanban,
    genie_npc_control,
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
    # the two full-power tools the Genie must never get
    assert {"scale_object", "kick_players"} <= names


def test_aw_roblox_genie_upstream_excludes_scale_object_and_kick_players():
    names = {t["name"] for t in aw_roblox_genie_server.TOOLS_SCHEMA}
    assert "scale_object" not in names
    assert "kick_players" not in names
    assert names == set(aw_roblox_genie_server._DISPATCH)
    # the 2 genie-kanban + 14 genie-npc-control tools this port found in the
    # real current agentic-workspace source (see genie_npc_control.py's
    # module docstring for why this is 16, not the 4 an earlier doc claimed)
    assert len(names) == 16


def test_genie_npc_control_is_a_strict_subset_of_npc_control():
    genie_names = set(genie_npc_control.DISPATCH)
    full_names = set(npc_control.DISPATCH)
    assert genie_names < full_names
    assert genie_names == full_names - {"scale_object", "kick_players", "set_lighting"}
    # same handler objects, not reimplemented copies
    for name in genie_names:
        assert genie_npc_control.DISPATCH[name] is npc_control.DISPATCH[name]


def test_two_separate_upstream_keys_not_one_merged_server():
    servers = self_register.build_mcp_servers(port=9030)
    assert set(servers) == {"aw-roblox", "aw-roblox-genie"}
    assert servers["aw-roblox"]["url"] != servers["aw-roblox-genie"]["url"]


def test_npc_control_tool_without_api_key_names_the_missing_config():
    text, is_error = npc_control.DISPATCH["npc_list"]({})
    assert is_error is False  # npc_list itself makes no HTTP call

    text, is_error = npc_control.DISPATCH["list_objects"]({})
    assert is_error is True
    assert config.PILOT_BACKEND_API_KEY in text


def test_roblox_gui_tool_without_exec_config_names_the_missing_config():
    text, is_error = roblox_gui.DISPATCH["roblox_gui_status"]({})
    assert is_error is True
    assert "studio_exec_base_url" in text


def test_genie_kanban_prefixes_title_and_never_lets_caller_skip_it():
    box = {}

    import urllib.request

    class _FakeResponse:
        status = 200

        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=30):
        import json as _json
        box["url"] = req.full_url
        box["body"] = _json.loads(req.data.decode())
        return _FakeResponse(b'{"ok": true, "page_id": "abc123"}')

    monkey = urllib.request.urlopen
    urllib.request.urlopen = _fake_urlopen
    try:
        import os
        os.environ["AW_WORKSPACE_API_KEY"] = "test-key"
        # caller already added the prefix itself -- must not be doubled
        text, is_error = genie_kanban.DISPATCH["create_genie_card"](
            {"title": "[GENIE] a house", "request": "quero uma casa",
             "player_name": "tester"})
    finally:
        urllib.request.urlopen = monkey
        os.environ.pop("AW_WORKSPACE_API_KEY", None)

    assert is_error is False
    assert box["body"]["title"] == "[GENIE] a house"
    assert box["body"]["source"] == "roblox-genie"
    assert "/api/apps/notion/kanban/cards" in box["url"]


def test_config_defaults():
    assert config.pilot_backend_url() == config.DEFAULT_PILOT_BACKEND_URL
    assert config.universe_id() == config.DEFAULT_UNIVERSE_ID
    assert config.default_place_name() == config.DEFAULT_PLACE_NAME
    assert config.studio_exec_base_url() == ""
    assert config.pilot_backend_api_key() == ""


def test_config_resolved_per_call_not_captured_at_import():
    box = {"cfg": {}, "secret": None}
    config.install_resolvers(lambda: box["cfg"], lambda name: box["secret"])
    assert config.pilot_backend_api_key() == ""
    box["secret"] = "sk-later"
    assert config.pilot_backend_api_key() == "sk-later"
    box["cfg"] = {"roblox_universe_id": "999"}
    assert config.universe_id() == "999"
