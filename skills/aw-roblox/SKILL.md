---
name: aw-roblox
description: Pilot the aw-roblox live game and Roblox Studio GUI directly (Frederico's own use, not the in-game Genie) through this app's aw-roblox MCP upstream — 25 tools split across roblox_gui_* (Studio automation) and npc/world control (pilot NPCs, move/spawn/duplicate objects, combat, lighting). Use when asked to pilot an NPC, move/spawn/duplicate a world object, publish a Studio change, or troubleshoot either.
---

# aw-roblox — full pilot surface (aw-roblox upstream)

Gateway tool prefix: `aw__aw_roblox__*` (25 tools). This is the FULL-power
surface — includes `scale_object` and `kick_players`, which the Genie's
own upstream (`aw-roblox-genie` / `aw__aw_roblox_genie__*`, see the
`aw-roblox-genie` skill) deliberately never gets. Reach for this skill
whenever you (Frederico, or an agent acting on your behalf) are piloting
the game directly — not when responding as the in-game Genie NPC.

**Scope note on this port (2026-08-18):** agentic-workspace's own
`aw-roblox` skill is almost entirely about two OTHER MCP servers —
`roblox-studio-mcp` and `roblox-studio-mcp-official` (Toolbox/Creator
Store asset search+insert, `execute_luau`, `screen_capture`, etc.).
Those were explicitly out of scope for this port (never requested, and
called out as such on the Kanban card that requested this app). None of
their tools exist here. If you need that content, it's still in
`agentic-workspace/skills/aw-roblox/SKILL.md`. This skill only covers the
two servers this app actually ships: `roblox_gui_*` (Studio GUI
automation) and the npc/world-control tools (piloting NPCs, moving/
spawning/duplicating objects, combat, lighting).

## Two tool groups, one upstream

**Studio GUI automation** (`roblox_gui_status`, `roblox_gui_ensure_open`,
`roblox_gui_publish`, `roblox_gui_close_place`, `roblox_gui_dismiss_dialogs`,
`roblox_gui_screenshot`, `roblox_gui_cleanup_stray_windows`,
`roblox_gui_publish_workflow`) — for the handful of Studio actions with no
API/Open Cloud equivalent at all: publishing the *live* Workspace of an
open Studio session (the only way to ship manually-inserted assets
together with code), releasing a stuck publish lock, dismissing an
unexpected dialog.

**OPEN QUESTION — which machine runs Studio, unresolved as of this port.**
The monolith reached a specific paired Windows machine (`aw-windows`) via
agents-platform's own exec channel, local to that monolith's host. That
mechanism doesn't exist here, and which host in this workspace would even
run Roblox Studio wasn't obvious when this app was built (same open
question as the aw-app-android-studio card — do not guess a host).
`studio_exec_base_url`/`studio_exec_client_id` (this app's Settings) are
left unset by default; every `roblox_gui_*` tool call fails with a clear
"not configured" message, never a silent timeout, until a real answer
lands here. See `roblox_app/mcp/roblox_gui.py`'s module docstring for the
exact HTTP contract whatever ends up serving that endpoint must speak.

**NPC/world control** (`npc_list`, `list_objects`, `npc_view`,
`npc_move_to`, `npc_fly_to`, `npc_kamehameha`, `move_object`,
`start_combat`, `stop_combat`, `duplicate_object`, `scale_object`,
`npc_follow`, `set_lighting`, `kick_players`, `npc_stop_follow`,
`npc_stop`, `spawn_object`) — a thin HTTP client to the
`roblox-pilot-backend` custom app's public subdomain (unchanged from the
monolith; container `aw-custom-roblox-pilot-backend` on the bare metal).
Needs `roblox_pilot_backend_api_key` set in this app's Settings — without
it, every one of these tools says so by name instead of a bare connection
failure. See the `aw-roblox-world-builder` skill for `spawn_object`'s full
JSON build-spec schema, and `aw-roblox-genie`'s skill for which of these
tools the in-game Genie NPC can also reach (a strict subset, on its own
separate upstream).

## Known gotchas carried over from the monolith

- **`roblox_gui_publish` can silently no-op** — no error, menu closes
  normally, but Open Cloud's `updated` timestamp for the universe never
  advances (root cause: a stuck save/publish lock server-side). Prefer
  `roblox_gui_publish_workflow` over calling `roblox_gui_publish` alone —
  it cross-checks `updated` and retries via close+reopen automatically
  (up to `max_attempts`), and force-shuts-down live servers once a
  publish is confirmed landed so new joins get the new code immediately.
  Inspect the response's `landed` field for ground truth, not just
  `success`.
- **Stray Studio windows accumulate.** `roblox_gui_close_place` (Ctrl+F4)
  shows the launcher instead of exiting the process, and each
  close+reopen cycle opens a *new* launcher window instead of reusing the
  last one. `roblox_gui_ensure_open`/`roblox_gui_publish_workflow` already
  call `roblox_gui_cleanup_stray_windows` on success — call it directly
  only to sweep up leftovers from before, or after manual GUI work done
  outside these tools.
- **Never publish game content that only exists as a manual Workspace
  placement.** This applies to whoever maintains the actual game source
  (`repos/aw-roblox`, not part of this app or this workspace) — see that
  repo's own `aw-roblox`/`aw-autoskill-aw-roblox-publish` notes in
  agentic-workspace for the full incident history (Workspace got silently
  wiped twice by the `rojo build` + Open Cloud pipeline because
  `default.project.json` doesn't map `Workspace`). `roblox_gui_publish*`
  here (Studio's own File → Publish) does NOT have this problem — it
  publishes the whole live DataModel, script content and manual
  placements together.
- **`force_shutdown_servers`** (only reachable via
  `roblox_gui_publish_workflow`'s retry, not its own tool) needs
  `roblox_api_key` (Open Cloud, `universe-messaging-service:publish`
  scope) set in this app's Settings — separate credential from
  `roblox_pilot_backend_api_key`.
