"""npc-control tool logic — pilot the aw-roblox NPCs from outside the game.

Ported from agentic-workspace's ``src/mcp/npc_control.py`` (stdio MCP
server there). Same thin HTTP client for the roblox-pilot-backend custom
app, over its PUBLIC subdomain — no change to that half, the backend
container (``aw-custom-roblox-pilot-backend``) is unchanged.

What DID change from the monolith: the API key no longer comes from
reading the backend app's own ``data/api_keys.json`` off a shared
filesystem (there is no shared filesystem between this app's container
and that one here) — it comes from this app's own secret store instead,
via :mod:`roblox_app.config`. If it isn't configured, every tool that
needs it says exactly that instead of a bare connection failure or a
silent timeout.

This module is imported by BOTH upstream servers
(:mod:`roblox_app.mcp.aw_roblox_server` for the full surface, and
:mod:`roblox_app.mcp.genie_npc_control` for the Genie's narrow subset) —
handler functions and ``TOOLS_SCHEMA`` are the single source of truth,
never duplicated.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .. import config

PILOTABLE_NPCS = ["goku", "vegeta", "piccolo", "hero", "naruto"]
# Move/fly-piloted (move_to/fly_to/stop) same as PILOTABLE_NPCS, but the
# dragon is NOT included in PILOTABLE_NPCS since that list also drives the
# automatic kamehameha auto-fire loop game-side and it's the default
# kamehameha target -- listed separately here so npc_list can still surface
# it as a valid move/fly target without implying it auto-attacks itself.
PILOTABLE_ENTITIES = PILOTABLE_NPCS + ["dragon", "cow", "dog", "horse"]

_NO_KEY = (
    f"No roblox-pilot-backend API key configured. Set '{config.PILOT_BACKEND_API_KEY}' "
    "in this app's Settings — it must match a live (non-revoked) entry in the "
    "roblox-pilot-backend container's own data/api_keys.json."
)


def _call(
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
    base: str = "pilot",
    timeout: int = 25,
) -> tuple[dict, int]:
    key = config.pilot_backend_api_key()
    if not key:
        return {"detail": _NO_KEY}, 500

    base_url = f"{config.pilot_backend_url()}/api/{base}"
    url = f"{base_url}{path}"
    if params:
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v is not None)
        if query:
            url = f"{url}?{query}"

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-Api-Key": key},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read())
        except Exception:
            err = {"detail": str(exc)}
        return err, exc.code
    except Exception as exc:
        return {"detail": str(exc)}, 500


def _npc_list(_args: dict) -> tuple[str, bool]:
    return json.dumps(
        {
            "npcs": PILOTABLE_NPCS,
            "move_fly_pilotable": PILOTABLE_ENTITIES,
            "note": "npc_kamehameha only works for 'npcs'; npc_move_to/npc_fly_to/npc_stop work for anything in 'move_fly_pilotable'.",
        }
    ), False


def _list_objects(_args: dict) -> tuple[str, bool]:
    result, status = _call("GET", "/objects", base="world")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _npc_view(args: dict) -> tuple[str, bool]:
    npc = args.get("npc")
    if not npc:
        return "npc is required", True
    result, status = _call("GET", "/state", params={"npc": npc}, base="pilot")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _npc_move_to(args: dict) -> tuple[str, bool]:
    npc = args.get("npc")
    if not npc:
        return "npc is required", True
    body = {"npc": npc, "action": "move_to"}
    if args.get("target_name"):
        body["target_name"] = args["target_name"]
    elif all(k in args and args[k] is not None for k in ("x", "y", "z")):
        body["target"] = {"x": args["x"], "y": args["y"], "z": args["z"]}
    else:
        return "provide either target_name or all of x/y/z", True
    result, status = _call("POST", "/command", body=body, base="pilot")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _npc_fly_to(args: dict) -> tuple[str, bool]:
    npc = args.get("npc")
    if not npc:
        return "npc is required", True
    body = {"npc": npc, "action": "fly_to"}
    if args.get("target_name"):
        body["target_name"] = args["target_name"]
    elif all(k in args and args[k] is not None for k in ("x", "y", "z")):
        body["target"] = {"x": args["x"], "y": args["y"], "z": args["z"]}
    else:
        return "provide either target_name or all of x/y/z (y is required for flight)", True
    result, status = _call("POST", "/command", body=body, base="pilot")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _npc_kamehameha(args: dict) -> tuple[str, bool]:
    npc = args.get("npc")
    if not npc:
        return "npc is required", True
    body = {"npc": npc, "action": "kamehameha"}
    if args.get("target_name"):
        body["target_name"] = args["target_name"]
    elif all(k in args and args[k] is not None for k in ("x", "y", "z")):
        body["target"] = {"x": args["x"], "y": args["y"], "z": args["z"]}
    # else: no target at all -- server defaults to "take a potshot at the dragon"
    result, status = _call("POST", "/command", body=body, base="pilot")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _move_object(args: dict) -> tuple[str, bool]:
    object_name = args.get("object_name")
    if not object_name:
        return "object_name is required", True
    if not all(k in args and args[k] is not None for k in ("x", "y", "z")):
        return "x, y, and z are all required", True
    body = {
        "action": "teleport_object",
        "object_name": object_name,
        "x": args["x"],
        "y": args["y"],
        "z": args["z"],
    }
    result, status = _call("POST", "/command", body=body, base="world")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _start_combat(args: dict) -> tuple[str, bool]:
    team_a = args.get("team_a")
    team_b = args.get("team_b")
    if not team_a or not isinstance(team_a, list):
        return "team_a is required and must be a non-empty list of names", True
    if not team_b or not isinstance(team_b, list):
        return "team_b is required and must be a non-empty list of names", True
    params = {"team_a": team_a, "team_b": team_b}
    for key in (
        "max_health", "damage_min", "damage_max", "attack_interval_min",
        "attack_interval_max", "flight_radius", "flight_speed", "respawn_delay",
    ):
        if args.get(key) is not None:
            params[key] = args[key]
    body = {"action": "start_combat", "params": params}
    result, status = _call("POST", "/command", body=body, base="world")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _stop_combat(args: dict) -> tuple[str, bool]:
    fighter = args.get("fighter")
    if not fighter:
        return "fighter is required (either fighter's name ends the whole fight)", True
    body = {"action": "stop_combat", "object_name": fighter}
    result, status = _call("POST", "/command", body=body, base="world")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _duplicate_object(args: dict) -> tuple[str, bool]:
    object_name = args.get("object_name")
    if not object_name:
        return "object_name is required", True
    if not all(k in args and args[k] is not None for k in ("x", "y", "z")):
        return "x, y, and z are all required", True
    body = {
        "action": "duplicate_object",
        "object_name": object_name,
        "new_name": args.get("new_name"),
        "x": args["x"],
        "y": args["y"],
        "z": args["z"],
    }
    if args.get("pilotable_id"):
        body["params"] = {"pilotable_id": args["pilotable_id"]}
    result, status = _call("POST", "/command", body=body, base="world")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _scale_object(args: dict) -> tuple[str, bool]:
    object_name = args.get("object_name")
    if not object_name:
        return "object_name is required", True
    scale_factor = args.get("scale_factor")
    if scale_factor is None:
        return "scale_factor is required", True
    body = {
        "action": "scale_object",
        "object_name": object_name,
        "scale_factor": scale_factor,
    }
    result, status = _call("POST", "/command", body=body, base="world")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _kick_players(args: dict) -> tuple[str, bool]:
    body = {"action": "kick_players"}
    if args.get("player_name"):
        body["player_name"] = args["player_name"]
    if args.get("message"):
        body["message"] = args["message"]
    result, status = _call("POST", "/command", body=body, base="world")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _set_lighting(args: dict) -> tuple[str, bool]:
    clock_time = args.get("clock_time")
    if clock_time is None:
        return "clock_time is required (0-24, e.g. 0 or 24 = midnight, 12 = noon, ~20 = night)", True
    body = {"action": "set_lighting", "x": clock_time}
    result, status = _call("POST", "/command", body=body, base="world")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _npc_follow(args: dict) -> tuple[str, bool]:
    npc = args.get("npc")
    if not npc:
        return "npc is required", True
    target_name = args.get("target_name")
    if not target_name:
        return "target_name is required", True
    body = {"npc": npc, "action": "follow", "target_name": target_name}
    result, status = _call("POST", "/command", body=body, base="pilot")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _npc_stop_follow(args: dict) -> tuple[str, bool]:
    npc = args.get("npc")
    if not npc:
        return "npc is required", True
    result, status = _call("POST", "/command", body={"npc": npc, "action": "stop_follow"}, base="pilot")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _npc_stop(args: dict) -> tuple[str, bool]:
    npc = args.get("npc")
    if not npc:
        return "npc is required", True
    result, status = _call("POST", "/command", body={"npc": npc, "action": "stop"}, base="pilot")
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


def _spawn_object(args: dict) -> tuple[str, bool]:
    prompt = args.get("prompt")
    if not prompt:
        return "prompt is required", True
    absolute_position = None
    if all(k in args and args[k] is not None for k in ("x", "y", "z")):
        absolute_position = [args["x"], args["y"], args["z"]]
    body = {
        "prompt": prompt,
        "requested_by_user_id": args.get("requested_by_user_id"),
        "target_user_id": args.get("target_user_id"),
        "absolute_position": absolute_position,
        "reuse_of": args.get("reuse_of"),
    }
    # Long-running: the backend calls an LLM to turn the prompt into a build
    # spec before returning -- 60s+ round-trips observed, so this needs a
    # much longer timeout than every other call here.
    result, status = _call("POST", "/request", body=body, base="spawn", timeout=190)
    if status != 200:
        return f"error ({status}): {result}", True
    return json.dumps(result), False


TOOLS_SCHEMA = [
    {
        "name": "npc_list",
        "description": (
            "List the NPC ids that can be piloted. Returns two sets: 'npcs' (Goku, "
            "Vegeta, Piccolo, Hero, Naruto -- these support npc_kamehameha too) and "
            "'move_fly_pilotable' (the same five plus the dragon and the farm animals "
            "-- cow, dog, horse -- npc_move_to/npc_fly_to/npc_stop work on anything in "
            "this list; an animal resumes its normal nearest-player-follow behavior "
            "the instant it arrives or gets npc_stop'd, same as the dragon resumes its "
            "own flight path). See also list_objects for everything else in the game "
            "world."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_objects",
        "description": (
            "List every top-level object currently in the live aw-roblox game's "
            "Workspace (e.g. 'Car', 'Genie', 'Modern house', 'Helicopter', pool/ground "
            "parts, ...) -- refreshed by the game server every ~15s. Use this to "
            "discover valid object_name values for move_object instead of guessing "
            "exact Instance names."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "npc_view",
        "description": (
            "Read what an NPC last reported: its position, status (idle/moving), and "
            "when it last checked in. This is the 'what is the NPC seeing/doing right "
            "now' read tool -- call it before deciding on a move or action."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "npc": {"type": "string", "description": "NPC id, e.g. 'vegeta'. See npc_list."},
            },
            "required": ["npc"],
        },
    },
    {
        "name": "npc_move_to",
        "description": (
            "Walk an NPC to a position. Either pass raw x/y/z coordinates, or "
            "target_name='dragon' to walk toward the dragon's current live position "
            "(resolved game-side). The NPC keeps its own ground height -- this is "
            "horizontal movement, not flight."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "npc": {"type": "string", "description": "NPC id, e.g. 'vegeta'."},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
                "target_name": {"type": "string", "description": "Named target instead of raw coords, e.g. 'dragon'."},
            },
            "required": ["npc"],
        },
    },
    {
        "name": "npc_fly_to",
        "description": (
            "Make an NPC fly to a 3D position and hover there -- unlike npc_move_to, "
            "this uses the real Y (altitude), ignores ground height entirely, and "
            "flies straight over obstacles instead of walking around them. Pass "
            "x/y/z, or target_name='genie' to hover above the genie's pedestal, or "
            "'dragon'/'car'/'player' at their live position. The NPC just stops and "
            "hovers in place once it arrives (everything here is anchored, no "
            "gravity) -- call npc_stop to cancel and let it resume normal ground "
            "behavior on the next move_to."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "npc": {"type": "string", "description": "NPC id, e.g. 'vegeta'."},
                "x": {"type": "number"},
                "y": {"type": "number", "description": "Altitude -- required when passing raw coordinates."},
                "z": {"type": "number"},
                "target_name": {"type": "string", "description": "Named target with a built-in altitude, e.g. 'genie'."},
            },
            "required": ["npc"],
        },
    },
    {
        "name": "npc_kamehameha",
        "description": (
            "Fire a kamehameha beam from an NPC. Pass x/y/z to aim at an exact point, "
            "target_name='dragon' to aim at the dragon's live position, or omit both to "
            "take the NPC's default random potshot at the dragon."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "npc": {"type": "string", "description": "NPC id, e.g. 'goku'."},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
                "target_name": {"type": "string", "description": "Named aim point, e.g. 'dragon'."},
            },
            "required": ["npc"],
        },
    },
    {
        "name": "move_object",
        "description": (
            "Teleport ANY named object already in the live aw-roblox game to an exact "
            "position, right now, with no rojo/Open Cloud publish needed -- for one-off "
            "runtime nudges (e.g. 'put the car back at spawn'). Resolves object_name "
            "against Workspace recursively (Model or loose BasePart, e.g. 'Car', "
            "'Goku', 'Genie'). This is a generic world-control channel, separate from "
            "npc_move_to/npc_fly_to (which drive an NPC's own AI loop toward a target "
            "over time) -- this just snaps the object straight there instantly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the Workspace object to move, e.g. 'Car'."},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
            },
            "required": ["object_name", "x", "y", "z"],
        },
    },
    {
        "name": "start_combat",
        "description": (
            "Make a TEAM of objects/NPCs/real players that ALREADY EXIST in the live "
            "aw-roblox game fight another team -- flying, chasing, periodic damage, "
            "health bars, KO + auto-respawn -- right now, no rojo/Open Cloud publish "
            "needed. team_a/team_b are each a list of names, so 1v1, many-vs-one, or "
            "any other size combo all work with the same call. Each name is resolved "
            "as an NPC/object in the world first, then as a connected player's "
            "username -- a real player's ACTUAL Humanoid health is never touched (only "
            "a separate on-screen combat health bar). A fighter can only be in one "
            "fight at a time; the call errors if any name is already fighting. All the "
            "tuning params are optional with sane defaults."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_a": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names on the first side, e.g. ['Vegeta'] or ['Hero','Piccolo'].",
                },
                "team_b": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names on the second side, e.g. ['Dragon'].",
                },
                "max_health": {"type": "number", "description": "Default 100."},
                "damage_min": {"type": "number", "description": "Default 8."},
                "damage_max": {"type": "number", "description": "Default 18."},
                "attack_interval_min": {"type": "number", "description": "Seconds between attacks, low end. Default 1.5."},
                "attack_interval_max": {"type": "number", "description": "Seconds between attacks, high end. Default 3.5."},
                "flight_radius": {"type": "number", "description": "How far each fighter roams around its current target while dodging/circling, in studs. Default 25."},
                "flight_speed": {"type": "number", "description": "Studs/sec. Default 22."},
                "respawn_delay": {"type": "number", "description": "Seconds a KO'd fighter stays down before health resets. Default 4."},
            },
            "required": ["team_a", "team_b"],
        },
    },
    {
        "name": "stop_combat",
        "description": "End a fight started with start_combat -- pass either fighter's name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fighter": {"type": "string", "description": "Either fighter's name from the fight you want to end."},
            },
            "required": ["fighter"],
        },
    },
    {
        "name": "duplicate_object",
        "description": (
            "Clone an object that ALREADY EXISTS in the live aw-roblox game's "
            "Workspace and place the copy at an exact position -- right now, no "
            "rojo/Open Cloud publish needed. Prefer this over spawn_object whenever a "
            "close match already exists in the world (see list_objects), especially "
            "for anything that needs to be DRIVEABLE/scripted: spawn_object can only "
            "ever produce static geometry, but a real Instance:Clone() of an existing "
            "object carries over its VehicleSeat, scripts and welds intact.\n\n"
            "Pass pilotable_id to also register the clone as a real pilotable NPC "
            "under that id -- it immediately works with npc_move_to/npc_fly_to/"
            "npc_follow/npc_stop just like any built-in NPC. Errors if that id is "
            "already taken (check npc_list first)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the EXISTING Workspace object to clone, e.g. 'Sports Car (red)'."},
                "new_name": {"type": "string", "description": "Name for the new clone. Defaults to '<object_name>Copy' if omitted."},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
                "pilotable_id": {"type": "string", "description": "Optional: register the clone as a pilotable NPC under this id."},
            },
            "required": ["object_name", "x", "y", "z"],
        },
    },
    {
        "name": "scale_object",
        "description": (
            "Resize a Model (NPC or any other Model-type Workspace object) in place, "
            "right now, with no rojo/Open Cloud publish needed. Uses Roblox's native "
            "Model:ScaleTo, which scales through the Humanoid/joint rig so animations "
            "keep working. scale_factor is an absolute multiplier of the object's "
            "ORIGINAL size (not cumulative)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Name of the Workspace object to scale, e.g. 'Goku'."},
                "scale_factor": {"type": "number", "description": "Absolute size multiplier, e.g. 3.0 for 3x original size."},
            },
            "required": ["object_name", "scale_factor"],
        },
    },
    {
        "name": "npc_follow",
        "description": (
            "Make an animal (cow/dog/horse) or the dragon continuously chase a named "
            "target's LIVE position every frame -- unlike npc_move_to/npc_fly_to "
            "(which walk to a fixed point and stop), this keeps re-tracking the "
            "target for as long as follow is active. Overrides the animal's default "
            "nearest-player-follow behavior (or the dragon's default lazy circular "
            "flight) until npc_stop_follow is called."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "npc": {"type": "string", "description": "cow, dog, horse, or dragon."},
                "target_name": {"type": "string", "description": "Name of the Workspace object/NPC to chase, e.g. 'Goku' or 'Car'."},
            },
            "required": ["npc", "target_name"],
        },
    },
    {
        "name": "set_lighting",
        "description": (
            "Set the live aw-roblox game's time of day right now, no republish "
            "needed. Also dims ambient brightness at night (roughly clock_time "
            "19-6) so it actually reads as dark, not just a dim sun."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "clock_time": {
                    "type": "number",
                    "description": "0-24 hour clock. 0 or 24 = midnight, 12 = noon, ~20 = evening/night.",
                },
            },
            "required": ["clock_time"],
        },
    },
    {
        "name": "kick_players",
        "description": (
            "Kick a real connected player out of the live aw-roblox game right now, "
            "or kick EVERYONE if player_name is omitted -- useful right before a "
            "force_shutdown_servers-driven publish. Separate from "
            "force_shutdown_servers (which kills the whole server process); this "
            "only disconnects the named player(s)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "player_name": {"type": "string", "description": "Exact Roblox username to kick. Omit to kick every connected player."},
                "message": {"type": "string", "description": "Message shown to the kicked player(s). Defaults to a generic 'removed from the game' message."},
            },
        },
    },
    {
        "name": "npc_stop_follow",
        "description": (
            "Turn OFF an animal's/the dragon's automatic follow behavior entirely -- "
            "unlike npc_stop (which only cancels a one-off move_to/fly_to), this "
            "disables auto-follow until npc_follow is requested again."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "npc": {"type": "string", "description": "cow, dog, horse, or dragon."},
            },
            "required": ["npc"],
        },
    },
    {
        "name": "npc_stop",
        "description": (
            "Cancel an NPC's current move_to/fly_to target (it stops/lands where it "
            "is) AND interrupts an in-progress kamehameha beam if one is still "
            "animating."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "npc": {"type": "string", "description": "NPC id, e.g. 'vegeta'."},
            },
            "required": ["npc"],
        },
    },
    {
        "name": "spawn_object",
        "description": (
            "Materialize ANY new structure or ambient effect in the live aw-roblox "
            "game from a plain-language description -- with NO server restart and NO "
            "republish needed. An LLM turns the prompt into a small JSON build spec "
            "(blocks/balls/cylinders and/or a particle-emitter spec) against a fixed "
            "schema -- Roblox disables loadstring() on published servers, so this "
            "NEVER runs raw generated code. Typically takes 10-60s.\n\n"
            "Routing: pass target_user_id when you know which player this is for -- "
            "placed near that player, on THEIR live server only. Omit for a broadcast "
            "to every live server near the spawn area instead.\n\n"
            "Placement: pass x/y/z together for an EXACT map coordinate, overriding "
            "the default near-player/near-origin placement.\n\n"
            "Module reuse: pass reuse_of=<the exact \"name\" of a previously-built "
            "spec> to vary an existing build instead of starting from scratch."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Plain-language description of what to build, e.g. 'uma fogueira'."},
                "target_user_id": {
                    "type": "integer",
                    "description": "Roblox numeric user id of the player to place this near / target that player's server. Omit to broadcast to every live server instead.",
                },
                "requested_by_user_id": {
                    "type": "integer",
                    "description": "Roblox numeric user id of whoever asked for this, if known. Independent of target_user_id.",
                },
                "x": {"type": "number", "description": "Exact map X coordinate. Must be passed together with y and z."},
                "y": {"type": "number", "description": "Exact map Y coordinate (height). Must be passed together with x and z."},
                "z": {"type": "number", "description": "Exact map Z coordinate. Must be passed together with x and y."},
                "reuse_of": {
                    "type": "string",
                    "description": "The exact \"name\" of a previously-built spec to use as a starting point, instead of building from scratch.",
                },
            },
            "required": ["prompt"],
        },
    },
]

DISPATCH = {
    "npc_list": _npc_list,
    "list_objects": _list_objects,
    "npc_view": _npc_view,
    "npc_move_to": _npc_move_to,
    "npc_fly_to": _npc_fly_to,
    "move_object": _move_object,
    "duplicate_object": _duplicate_object,
    "start_combat": _start_combat,
    "stop_combat": _stop_combat,
    "scale_object": _scale_object,
    "npc_kamehameha": _npc_kamehameha,
    "spawn_object": _spawn_object,
    "npc_follow": _npc_follow,
    "npc_stop_follow": _npc_stop_follow,
    "kick_players": _kick_players,
    "set_lighting": _set_lighting,
    "npc_stop": _npc_stop,
}
