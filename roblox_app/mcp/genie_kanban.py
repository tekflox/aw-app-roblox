"""genie-kanban tool logic — the Genie NPC's own scoped Kanban access.

Ported from agentic-workspace's ``src/mcp/genie_kanban.py``, deliberately
narrow compared to the full aw-kanban MCP (aw-app-notion) -- the Genie is
a chat NPC any random player can talk to, so giving it the full Kanban
toolset would let a player's message indirectly move/derail unrelated
Kanban work via prompt injection. This server exposes exactly two tools:

- ``create_genie_card``: creates a card, but the "[GENIE] " title prefix
  and ``source="roblox-genie"`` are enforced server-side (never
  caller-controlled), so every card this tool can create is unambiguously
  identifiable.
- ``list_genie_cards``: reads cards back, but hard-filters to
  ``source=roblox-genie`` server-side -- the Genie can never see/list any
  other card on the board.

**What changed from the monolith:** the old awserv HTTP API
(``http://127.0.0.1:9123/api/notion/kanban/create-task`` /
``.../genie-cards``) does not exist in this decoupled workspace. Kanban
here is aw-app-notion's own REST mirror
(``/api/apps/notion/kanban/cards``), reached the same way
aw-app-agents-platform-runners' ``kanban_dispatch.BoardClient`` reaches
it -- over the workspace API, ``AW_WORKSPACE_API_KEY`` in the header.
This app is Tier-1 in-process (same runtime as aw-app-notion), so
loopback is the normal path here, not a fallback for a stdio child
outside the workspace's own network namespace.

There is no Telegram-approval step to describe to a player anymore
either (aw-kanban skill: "create_kanban_task creates the card and
stops") -- the monolith's own workflow already told players their wish
was "noted", not "done immediately", so that part of the tool
description carries over unchanged.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

NOTION_PREFIX = "/api/apps/notion"
API_URL_VAR = "AW_WORKSPACE_API_URL"
API_KEY_VAR = "AW_WORKSPACE_API_KEY"

GENIE_PREFIX = "[GENIE] "
GENIE_SOURCE = "roblox-genie"
DEFAULT_TARGET_SLUG = "system-investigations"

_NO_KEY = (
    f"{API_KEY_VAR} is not set in this process's environment -- this app is Tier-1 "
    "in-process so it should always be present; if it's missing, the workspace was "
    "restarted with a broken env and needs another restart."
)


def _base_url() -> str:
    port = os.environ.get("AW_PORT", "9030")
    return (os.environ.get(API_URL_VAR) or f"http://127.0.0.1:{port}").rstrip("/")


def _api(method: str, path: str, body: dict | None = None) -> tuple[dict, int]:
    key = os.environ.get(API_KEY_VAR)
    if not key:
        return {"error": _NO_KEY}, 0
    url = f"{_base_url()}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-Api-Key": key}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code
        except Exception:
            return {"error": f"HTTP {e.code}"}, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "request"


def _create_genie_card(args: dict) -> tuple[str, bool]:
    title = (args.get("title") or "").strip()
    if not title:
        return "title is required", True
    request_text = (args.get("request") or "").strip()
    if not request_text:
        return "request is required (what the player actually asked for)", True
    player_name = (args.get("player_name") or "").strip()

    # Strip any "[GENIE]"/"[genie]" prefix the caller might have already
    # added, then apply it exactly once -- the prefix is what makes
    # list_genie_cards' filtering meaningful, so it can't be caller-skipped
    # or duplicated.
    clean_title = re.sub(r"^\[GENIE\]\s*", "", title, flags=re.IGNORECASE).strip()
    full_title = f"{GENIE_PREFIX}{clean_title}"

    description = f"Pedido de {player_name or 'um jogador'} via chat com o gênio: {request_text}"
    input_text = (
        f"Pedido feito por um jogador ao NPC gênio do aw-roblox (repos/aw-roblox). "
        f"Jogador: {player_name or 'desconhecido'}. Pedido original: \"{request_text}\". "
        f"Implemente em src/ServerScriptService/WorldSetup.server.lua (ou o arquivo mais "
        f"apropriado) seguindo os padrões já existentes no arquivo, publique via a skill "
        f"aw-autoskill-aw-roblox-publish (rojo build + Open Cloud + force_shutdown_servers)."
    )

    payload = {
        "title": full_title,
        "finding_key": f"genie:{_slugify(clean_title)}",
        "priority": "Média",
        "agent_slug": "coder-sonnet",
        "target_slug": DEFAULT_TARGET_SLUG,
        "input_text": input_text,
        "description": description[:200],
        "plan": "",
        "source": GENIE_SOURCE,
        "tags": ["genie"],
    }

    body, status = _api("POST", f"{NOTION_PREFIX}/kanban/cards", payload)
    if status == 200 and body.get("ok", True) is not False:
        result = {
            "page_id": body.get("page_id"),
            "is_new": body.get("is_new", True),
            "title": full_title,
        }
        return json.dumps(result), False
    return json.dumps(body, indent=2), True


def _list_genie_cards(args: dict) -> tuple[str, bool]:
    status_filter = (args.get("status") or "").strip()
    query = urllib.parse.urlencode({"source": GENIE_SOURCE, "status": status_filter, "limit": 50})
    body, http_status = _api("GET", f"{NOTION_PREFIX}/kanban/cards?{query}")
    if http_status != 200:
        return json.dumps(body, indent=2), True
    return json.dumps(body, indent=2), False


TOOLS_SCHEMA = [
    {
        "name": "create_genie_card",
        "description": (
            "Create a Kanban card asking for a NEW feature/change to the aw-roblox game "
            "(e.g. a new NPC, animal, building, vehicle, or any request that needs real "
            "code) that a player just asked you (the genie) for. Use this when a player's "
            "wish clearly needs code/content to be built, e.g. 'faz um cavalo', 'constrói "
            "uma casa nova', 'quero um carro novo' -- NOT for questions, small talk, or "
            "anything you can just answer/roleplay directly. The card title is always "
            "prefixed '[GENIE] ' automatically -- tell the player their wish has been "
            "noted/sent to the workshop, not that it's done immediately."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short card title, e.g. 'Novo cavalo no jogo'. The '[GENIE] ' prefix is added automatically."},
                "request": {"type": "string", "description": "The player's actual wish/request, close to their own words."},
                "player_name": {"type": "string", "description": "The requesting player's name/username, if known."},
            },
            "required": ["title", "request"],
        },
    },
    {
        "name": "list_genie_cards",
        "description": (
            "List Kanban cards previously created via create_genie_card -- ONLY cards "
            "with source=roblox-genie, nothing else on the board is visible through this "
            "tool. Use to check on a wish's status if a player asks 'e aí, meu pedido saiu?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Optional status filter (e.g. 'Backlog', 'Done'). Omit to get the default set.",
                },
            },
        },
    },
]

DISPATCH = {
    "create_genie_card": _create_genie_card,
    "list_genie_cards": _list_genie_cards,
}
