---
repo: architecture
path: docs/architecture/aw-app-roblox.md
source: generated
edited: false
checksum: sha256:aea299b1e488f9a447d4df5673a6f1b48f121410175f8b418d48343923ff2893
---
# Roblox

- **repo**: aw-app-roblox
- **layer**: app
- **technologies**: python
- **health** (derived): planned

Ports agentic-workspace's four Roblox MCP servers (roblox-gui, npc-control, genie-kanban, genie-npc-control) into aw-workspace as TWO separate upstreams: aw-roblox (full pilot surface — Studio GUI automation + NPC/world control, 25 tools) and aw-roblox-genie (the in-game Genie NPC's narrow, chat-injection-safe subset, 16 tools — no scale_object/kick_players, Kanban access hard-filtered to its own cards). Kept as two upstreams on purpose: merging them would hand the Genie tools it must never reach.

## Connections
- `http` → **aw-workspace** — routes mounted at /api/apps/roblox
- `other` → **aw-app-notion** — create_genie_card/list_genie_cards call aw-app-notion's Kanban REST mirror (/api/apps/notion/kanban/cards) over the loopback workspace API
- `stdio-mcp` → **mcp-gateway** — MCP surface aggregated by the gateway

## MCP tools
- `create_genie_card`
- `duplicate_object`
- `kick_players`
- `list_genie_cards`
- `list_objects`
- `move_object`
- `npc_fly_to`
- `npc_follow`
- `npc_kamehameha`
- `npc_list`
- `npc_move_to`
- `npc_stop`
- `npc_stop_follow`
- `npc_view`
- `roblox_gui_cleanup_stray_windows`
- `roblox_gui_close_place`
- `roblox_gui_dismiss_dialogs`
- `roblox_gui_ensure_open`
- `roblox_gui_publish`
- `roblox_gui_publish_workflow`
- `roblox_gui_screenshot`
- `roblox_gui_status`
- `scale_object`
- `set_lighting`
- `spawn_object`
- `start_combat`
- `stop_combat`

## Requirements
_none documented_
