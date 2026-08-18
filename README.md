# aw-app-roblox

Ports agentic-workspace's four Roblox MCP servers into aw-workspace as
**two separate MCP upstreams from one app** — not four servers, not one
merged server. The split is deliberate and security-relevant; read
"Why two upstreams" below before changing it.

| Upstream | Gateway prefix | Tools | Who reaches it |
|---|---|---|---|
| `aw-roblox` | `aw__aw_roblox__*` | 25 (`roblox_gui_*` × 8 + npc/world control × 17) | Frederico, or any agent acting for him — full power |
| `aw-roblox-genie` | `aw__aw_roblox_genie__*` | 16 (`create_genie_card`/`list_genie_cards` × 2 + a scoped npc/world subset × 14) | the in-game Genie NPC any random player can chat with |

## Why two upstreams

The Genie NPC is talked to by any random player — every message is a
potential prompt-injection attempt. `aw-roblox`'s full surface includes
`scale_object` (resize anything) and `kick_players` (disconnect anyone);
`aw-roblox-genie` never carries either, enforced by a module-load-time
assertion in `roblox_app/mcp/aw_roblox_genie_server.py` and
`genie_npc_control.py`, not just an access-control list an agent config
could misconfigure. `create_genie_card`/`list_genie_cards` are similarly
hard-scoped to `source=roblox-genie` cards only — the Genie can never see
or touch anything else on the Kanban board. See the `aw-roblox-genie`
skill for the full rationale.

## Source servers this ports

From `agentic-workspace/src/mcp/`:

- `roblox_gui.py` (8 tools) + `tools/roblox-studio-gui/roblox_gui.py` —
  Roblox Studio GUI automation, merged into one module here
  (`roblox_app/mcp/roblox_gui.py`).
- `npc_control.py` (17 tools) → `roblox_app/mcp/npc_control.py`.
- `genie_kanban.py` (2 tools) → `roblox_app/mcp/genie_kanban.py`.
- `genie_npc_control.py` — the real current source exposes **14** tools
  (everything `npc_control` has except `scale_object`, `kick_players`,
  `set_lighting`), not the 2 an earlier description of this port claimed.
  Ported faithfully at 14 — see `genie_npc_control.py`'s module docstring.

## What changed from the monolith

- **No shared filesystem, no stdio subprocess.** Both upstreams are
  served in-process over Streamable HTTP (`POST /api/apps/roblox/mcp` and
  `/mcp-genie`), self-registered into this app's own `mcp.json` — same
  pattern as aw-app-google-maps. `npc_control`'s API key no longer comes
  from reading `roblox-pilot-backend`'s `data/api_keys.json` off a shared
  disk; it's a config secret this app owns (`roblox_pilot_backend_api_key`).
- **`genie_kanban` re-targeted.** The monolith's awserv HTTP API
  (`127.0.0.1:9123/api/notion/kanban/create-task`) doesn't exist in this
  decoupled workspace. Kanban here is aw-app-notion's REST mirror
  (`/api/apps/notion/kanban/cards`), reached over loopback +
  `AW_WORKSPACE_API_KEY` — same approach as
  `aw-app-agents-platform-runners`'s `kanban_dispatch.BoardClient`.
- **Studio GUI automation's exec host is an open question.** The monolith
  reached a specific Windows machine via agents-platform's own
  `/api/clients/{id}/exec`, local to that host — that mechanism doesn't
  exist here, and which machine in this workspace would run Studio wasn't
  obvious (same open question as the aw-app-android-studio card). Left
  fully config-driven (`studio_exec_base_url`/`studio_exec_client_id`,
  unset by default) rather than guessed — every `roblox_gui_*` tool fails
  with a clear "not configured" message until it's set. See
  `roblox_app/mcp/roblox_gui.py`'s module docstring for the exact HTTP
  contract the endpoint needs to speak.
- **`roblox_api_key`/`roblox_universe_id`** (used by
  `force_shutdown_servers`, part of `roblox_gui_publish_workflow`) come
  from this app's config now, not a `.env` file on a shared `repos/`
  checkout — the actual game repo (`repos/aw-roblox`) isn't part of this
  app or this workspace at all (out of scope for this port).

## Configuration

Settings (`POST /api/apps/roblox/settings` for the two secrets, or the
generic config path for everything else):

| Key | Secret? | Default |
|---|---|---|
| `roblox_pilot_backend_url` | no | `https://roblox-pilot-backend.app.aw.tekflox.com` |
| `roblox_pilot_backend_api_key` | yes | — required for every `npc_control`/genie-npc tool |
| `roblox_universe_id` | no | `2019066227` |
| `roblox_api_key` | yes | — only needed for `force_shutdown_servers` |
| `roblox_place_name` | no | `fredericowu's Place` |
| `studio_exec_base_url` | no | unset — open question, see above |
| `studio_exec_client_id` | no | unset |

## Verifying the install

1. Gateway serves two separate upstreams: 25 tools under `aw__aw_roblox__*`,
   16 under `aw__aw_roblox_genie__*`.
2. `kick_players`/`scale_object`/`set_lighting` never appear under the
   `aw_roblox_genie` prefix — the test that actually matters (see
   `tests/test_mcp.py`).
3. `roblox_gui_status` and `npc_list`/`list_objects` either respond
   against the real backend, or fail by naming the exact missing config —
   never a silent timeout.

## Skills

`aw-roblox` (Frederico's direct use), `aw-roblox-genie` (the Genie's
persona + narrow surface), `aw-roblox-world-builder` (the `spawn_object`
JSON build-spec schema), `aw-autoskill-aw-roblox-publish` (the
Rojo + Open Cloud publish recipe for whoever maintains the actual game
repo — not part of this app).

## Out of scope for this port

`roblox-studio-mcp` / `roblox-studio-mcp-official` (Toolbox/Creator Store
asset search+insert, `execute_luau`, etc.) exist in the monolith but were
never requested for this app. Provisioning/testing the Studio host is
also out of scope — see `studio_exec_base_url` above.
