---
name: aw-autoskill-aw-roblox-publish
description: Build and publish Lua code changes to the aw-roblox game (repos/aw-roblox, NOT part of this app/workspace) from a sandbox — Rojo build + Roblox Open Cloud API, no Studio needed — plus this app's force_shutdown_servers step to push the change to already-running servers. Use when asked to add/edit game logic (WorldSetup.server.lua etc.) and ship it to the live place.
---

# aw-roblox — publishing code changes without Studio

**Scope note on this port (2026-08-18):** `repos/aw-roblox` (the actual
Lua game source, Rojo project) is NOT part of this app or this
workspace — porting the game repo itself was out of scope for the
Kanban card that created this app. This skill is kept anyway because it
documents a real operational recipe that references this app's
`roblox_gui_publish_workflow` tool (step 5 below) and stays useful
reference for whoever maintains `repos/aw-roblox` in agentic-workspace
directly. Steps 1-4 and 6 below assume a checkout of that repo, which
this workspace does not have.

`repos/aw-roblox` syncs via Rojo, but you don't need Roblox Studio open to
ship a code change — Rojo can build the place file headlessly and the
Roblox Open Cloud API accepts a direct publish. This is the edit → verify
→ publish loop for `src/**/*.lua`; it's separate from this app's
`roblox_gui_*` Studio GUI automation (used only for actions with no API
equivalent — see the `aw-roblox` skill).

## ⚠️ This pipeline silently wipes Workspace — check before you run it

`default.project.json` only maps `ServerScriptService`, `StarterGui`,
`ReplicatedStorage`, and `StarterPlayer/StarterPlayerScripts` — **not**
`Workspace`. `rojo build` always generates a *complete new place* from the
project tree, so any service not listed (Workspace) comes back **empty**.
Script-generated content (pool, animals, Goku, tower, playground…) is fine —
`WorldSetup.server.lua` recreates it at runtime regardless. But anything
manually placed straight into Workspace via Toolbox/`insert_asset` (the
house, the sports car) is **not** tracked by Rojo/git at all, and this
pipeline erases it with no warning and no recovery path (confirmed to
happen for real, twice — see the `aw-roblox` skill in agentic-workspace's
own knowledge base for the incident notes).

**Before running this pipeline for a script-only change**, check whether
the live Studio session currently has any manually-inserted Workspace
content that isn't yet durably published — if so, use Studio's own
**File → Publish to Roblox** instead (this app's `roblox_gui_publish` /
`roblox_gui_publish_workflow` tools — publishes the whole live DataModel,
script + manual placements together, no wipe). Only use this `rojo build`
+ Open Cloud pipeline when you're sure Workspace has nothing worth
losing, or when no manual assets have been added since the last publish.

## One-time setup in `repos/aw-roblox` (agentic-workspace, not here)

- `.env` (gitignored) holds `ROBLOX_API_KEY` (scoped to `universe-places:write`
  for this experience only), `ROBLOX_UNIVERSE_ID`, `ROBLOX_PLACE_ID`.
- Rojo CLI binary — reinstall from the GitHub release zip (`rojo-rbx/rojo`)
  if missing.

## The loop (repeat per change)

1. Edit the `.lua` file(s) under `src/` in `repos/aw-roblox`.
2. Syntax-check with `luac5.4` (or `luac5.3`) before building — a Lua
   syntax error fails silently deep in `rojo build` otherwise:
   ```bash
   cd repos/aw-roblox
   luac5.4 -p src/ServerScriptService/WorldSetup.server.lua && echo SYNTAX_OK
   ```
   **False positive to ignore:** `luac5.4`/`luac5.3` will reject Luau-only
   syntax like the `+=`/`-=` compound-assignment operators (`"unexpected
   symbol near '+='"`) — that's standard Lua rejecting valid Luau, not a
   real bug in the script. If the only error is on a `+=`/`-=`/`*=`/`/=`
   line, treat the syntax check as passed and proceed to `rojo build`
   (Roblox's own Luau runtime accepts the file fine).
3. Build the place file:
   ```bash
   rojo build default.project.json -o aw-roblox.rbxlx
   ```
4. Publish via Open Cloud API:
   ```bash
   cd repos/aw-roblox && set -a && source .env && set +a
   curl -s -X POST \
     "https://apis.roblox.com/universes/v1/${ROBLOX_UNIVERSE_ID}/places/${ROBLOX_PLACE_ID}/versions?versionType=Published" \
     -H "x-api-key: ${ROBLOX_API_KEY}" \
     -H "Content-Type: application/xml" \
     --data-binary @aw-roblox.rbxlx \
     -w "\nHTTP_STATUS:%{http_code}\n"
   ```
   `HTTP_STATUS:200` with a `{"versionNumber": N}` body means it's live.
5. **Force any already-running server to shut down** so nobody stays stuck
   on the pre-publish version until their server happens to empty out —
   Roblox only serves the new version to servers that start *after* the
   publish, existing ones keep running the old code. Via this app (not a
   standalone script anymore — `force_shutdown_servers` was folded into
   `roblox_gui_publish_workflow`'s retry logic, see
   `roblox_app/mcp/roblox_gui.py`):
   - Preferred: call `roblox_gui_publish_workflow` (this app's `aw-roblox`
     upstream) instead of steps 3-4 by hand — it already does the
     Rojo-independent Studio publish, cross-checks `updated`, and calls
     `force_shutdown_servers` once it confirms the publish landed.
   - If you did steps 3-4 by hand (this Rojo/Open Cloud pipeline is a
     separate path from Studio's own publish), there is currently no
     standalone `force_shutdown_servers`-only MCP tool in this app — it
     only fires as part of `roblox_gui_publish_workflow`'s success path.
     Call that tool anyway (it re-publishes via Studio too, which is
     idempotent) or hit Open Cloud's MessagingService "Publish Message"
     API directly on the `ForceShutdownOnPublish` topic with
     `ROBLOX_API_KEY`/`ROBLOX_UNIVERSE_ID` — see
     `roblox_app/mcp/roblox_gui.py`'s `force_shutdown_servers()` for the
     exact request shape if you need to replicate it standalone.
   `VersionWatcher.server.lua` (`ServerScriptService`, agentic-workspace)
   subscribes to that topic in-game and calls `game:Shutdown()` when it
   fires. Every kicked player rejoins straight into a fresh server already
   on the new version.
6. `git add -A && git commit` the source changes in `repos/aw-roblox` (the
   built `.rbxlx` itself is gitignored, only source is tracked).

## Gotchas actually hit

- Don't skip step 2 — several publish attempts in the same feature (farm
  pen, Goku build) silently produced a stale/broken place because a Lua
  syntax error wasn't caught before `rojo build`.
- `versionType=Published` (not `Saved`) is required for the change to be
  visible to players immediately, not just as a draft version.
- Only one Studio session can have the place open at a time — relevant if
  a human is also editing live (a stuck lock, see the `aw-roblox` skill's
  409-conflict note, `roblox_gui_publish_workflow`'s retry exists exactly
  for this).
- The Open Cloud API key needs the `universe-messaging-service:publish`
  scope in the Roblox Creator Dashboard in addition to `universe-places:write`
  for step 5 to work — the key was originally scoped for publish-only, so
  this may need a one-time manual scope addition (human-only, no API for
  it). If it 403s, that's the first thing to check. In this app, that's
  the `roblox_api_key` config knob (Settings) — see the `aw-roblox` skill.
