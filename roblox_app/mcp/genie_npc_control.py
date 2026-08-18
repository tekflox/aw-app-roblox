"""genie-npc-control tool logic — the Genie NPC's own scoped NPC/object control.

Ported from agentic-workspace's ``src/mcp/genie_npc_control.py``.
Deliberately NARROW compared to the full npc-control surface
(:mod:`roblox_app.mcp.npc_control`) -- reuses its exact same handler
functions (imported directly, no duplicated HTTP logic) but leaves out
``scale_object`` and ``kick_players``: a random player's chat message
with the Genie should never be able to resize the world or disconnect
anyone, so those two stay exclusive to the ``aw-roblox`` upstream (used
directly, not reachable from the Genie's conversation).

**Tool count note (2026-08-18 port):** the Kanban card that requested
this port describes this server as exposing 2 tools (``list_objects``,
``npc_list``). The actual source in agentic-workspace, read fresh for
this port, exposes 14 -- everything npc-control has except
``scale_object`` and ``kick_players`` (also absent here, same as there).
The card's count looks like a documentation error, not a deliberate
narrowing done since the KB doc was written: the source docstring's own
security rationale is scoped to exactly those two tools, not to an
overall tool-count cap, and every one of the 14 already goes through
npc_control's own argument validation. Porting the real 14-tool file
preserves the actual anti-prompt-injection boundary (no scale/kick);
truncating to 2 tools would just be inventing a narrower server nothing
in either repo ever shipped. Flagged on the Kanban card for a human to
confirm.
"""
from __future__ import annotations

from . import npc_control

_NAMES = [
    "npc_list",
    "list_objects",
    "npc_view",
    "npc_move_to",
    "npc_fly_to",
    "npc_follow",
    "npc_stop_follow",
    "npc_kamehameha",
    "move_object",
    "duplicate_object",
    "start_combat",
    "stop_combat",
    "npc_stop",
    "spawn_object",
]

_BY_NAME = {t["name"]: t for t in npc_control.TOOLS_SCHEMA}

TOOLS_SCHEMA = [_BY_NAME[name] for name in _NAMES]
DISPATCH = {name: npc_control.DISPATCH[name] for name in _NAMES}

assert not {"scale_object", "kick_players", "set_lighting"} & set(DISPATCH), (
    "genie-npc-control must never reach scale_object/kick_players/set_lighting -- see module docstring"
)
