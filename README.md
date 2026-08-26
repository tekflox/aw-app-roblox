# aw-app-roblox

Pilot the live aw-roblox game and Roblox Studio directly — Frederico's own
full-power surface. One MCP upstream, `aw-roblox`
(`aw__aw_roblox__*` on the gateway, route `/api/apps/roblox/mcp`), 25
tools: `roblox_gui_*` × 8 (Studio GUI automation) + npc/world control × 17
(move, spawn, duplicate objects, combat, lighting, `scale_object`,
`kick_players`).

## Split from the Genie (2026-08-26)

This app used to also ship a second, narrower upstream (`aw-roblox-genie`)
for the in-game Genie NPC that any random player can chat with. That
moved to its own app, **`aw-app-roblox-genie`**, so the chat-injectable
surface a player's message can reach never shares a repo/permission
boundary with this app's full power (`scale_object`, `kick_players`).
See that app's README for the security rationale and the shared-secret
gotcha (`roblox_pilot_backend_api_key` has to be configured in both apps).

## Source servers this ports

From `agentic-workspace/src/mcp/`:

- `roblox_gui.py` (8 tools) + `tools/roblox-studio-gui/roblox_gui.py` —
  Roblox Studio GUI automation, merged into one module here
  (`roblox_app/mcp/roblox_gui.py`).
- `npc_control.py` (17 tools) → `roblox_app/mcp/npc_control.py`.

## What changed from the monolith

- **No shared filesystem, no stdio subprocess.** Served in-process over
  Streamable HTTP (`POST /api/apps/roblox/mcp`), self-registered into
  this app's own `mcp.json` — same pattern as aw-app-google-maps.
  `npc_control`'s API key no longer comes from reading
  `roblox-pilot-backend`'s `data/api_keys.json` off a shared disk; it's a
  config secret this app owns (`roblox_pilot_backend_api_key`).
- **Studio GUI automation's exec host** goes through **aw-remote-hosts**
  (`studio_remote_host_id` in Settings — an id/slug/hostname from
  `GET /api/apps/roblox/remote-hosts`), not the monolith's
  agents-platform-specific `/api/clients/{id}/exec` channel, which
  doesn't exist in this decoupled workspace. See
  `roblox_app/remote_host_client.py` and `roblox_app/mcp/roblox_gui.py`'s
  module docstring. The app's own **Roblox** window (Apps grid) has a
  panel to set the host, provision its Python deps (pywinauto/Pillow/
  pywin32), and test the connection — no agent needed for setup.
- **`roblox_api_key`/`roblox_universe_id`** (used by
  `force_shutdown_servers`, part of `roblox_gui_publish_workflow`) come
  from this app's config now, not a `.env` file on a shared `repos/`
  checkout — the actual game repo (`repos/aw-roblox`) isn't part of this
  app or this workspace at all (out of scope for this port).

## Configuration

Settings (`POST /api/apps/roblox/settings` for the two secrets, or the
generic config path for everything else — or the app's own **Roblox**
window for `studio_remote_host_id`):

| Key | Secret? | Default |
|---|---|---|
| `roblox_pilot_backend_url` | no | `https://roblox-pilot-backend.app.aw.tekflox.com` |
| `roblox_pilot_backend_api_key` | yes | — required for every `npc_control` tool |
| `roblox_universe_id` | no | `2019066227` |
| `roblox_api_key` | yes | — only needed for `force_shutdown_servers` |
| `roblox_place_name` | no | `fredericowu's Place` |
| `studio_remote_host_id` | no | unset — required for every `roblox_gui_*` tool |

## Verifying the install

1. Gateway serves 25 tools under `aw__aw_roblox__*`.
2. `roblox_gui_status` and `npc_list`/`list_objects` either respond
   against the real backend, or fail by naming the exact missing config —
   never a silent timeout.
3. The **Roblox** window's "Test connection" button round-trips
   `roblox_gui_status` against `studio_remote_host_id`.

## Skills

`aw-roblox` (Frederico's direct use), `aw-roblox-world-builder` (the
`spawn_object` JSON build-spec schema), `aw-autoskill-aw-roblox-publish`
(the Rojo + Open Cloud publish recipe for whoever maintains the actual
game repo — not part of this app).

## Out of scope for this port

`roblox-studio-mcp` / `roblox-studio-mcp-official` (the official Roblox
Studio MCP, Toolbox/Creator Store asset search+insert, `execute_luau`,
etc.) exist in the monolith but were never ported here. The Genie NPC's
tools/skill/agent live in `aw-app-roblox-genie` instead of here.
