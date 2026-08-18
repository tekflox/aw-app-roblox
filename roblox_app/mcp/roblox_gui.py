"""roblox-gui tool logic — Roblox Studio GUI automation as MCP tools.

Ported and merged from two agentic-workspace files: the low-level
pywinauto-over-exec library (``tools/roblox-studio-gui/roblox_gui.py``)
and the thin MCP wrapper that added the publish-workflow retry
(``src/mcp/roblox_gui.py``). One file here since nothing else in this app
consumes the raw library separately.

**Open question, do not guess (per the Kanban card for this port):** the
monolith reached a Windows machine with Roblox Studio open via
agents-platform's own ``POST /api/clients/{client_id}/exec`` — a
long-poll NDJSON exec channel to a specific paired client
(``aw-windows``, hardcoded client id), local to that monolith's host.
That mechanism does not exist in this decoupled workspace, and which
host would even run Studio is not obvious (same open question as the
aw-app-android-studio card). So the exec endpoint is entirely
config-driven here (``studio_exec_base_url`` / ``studio_exec_client_id``,
see :mod:`roblox_app.config`) and defaults to unset — every tool in this
module fails with a clear "not configured" message rather than a silent
timeout until a real answer lands on the Kanban card. Whatever serves
that endpoint must speak the same contract ``_exec_remote`` expects
below: ``POST {base_url}/api/clients/{client_id}/exec`` with
``{"command": <str>, "timeout": <int>}``, streaming newline-delimited
JSON objects shaped either ``{"stream": "stdout"|"stderr", "data": str}``
or ``{"done": true, "returncode": int}``.

Everything below the exec transport (the pywinauto script that runs on
the Windows side, the publish-workflow retry logic, window pinning,
stray-window cleanup) is untouched from the monolith — only WHERE the
command gets executed changed.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request

from .. import config

DEFAULT_PLACE_NAME = config.DEFAULT_PLACE_NAME
FORCE_SHUTDOWN_TOPIC = "ForceShutdownOnPublish"

# Fixed window geometry every action pins Studio to first. Screen
# coordinates baked into the actions below are relative to THIS rect --
# change one, change the other.
WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H = 0, 0, 1600, 1000

_RESULT_MARKER = "###AW_GUI_RESULT###"

_NO_EXEC = (
    "studio_exec_base_url / studio_exec_client_id are not configured for this app "
    "(Settings). This tool needs a live HTTP exec channel to a machine with Roblox "
    "Studio open and signed in -- see roblox_app/mcp/roblox_gui.py's module "
    "docstring for the contract it expects, and this port's Kanban card for the "
    "open question of which host that should be."
)

# ─── Windows-side script (never touches disk there) ────────────────────────
#
# Dispatches on __ACTION__, baked in at call time. Always ends by printing
# exactly one line starting with _RESULT_MARKER + a JSON blob -- that's the
# only line trusted here; everything else on stdout/stderr is diagnostic
# noise (pywinauto warnings etc).
_WINDOWS_SCRIPT = r'''
import base64, json, sys, time
from pywinauto import Application, Desktop
import pywinauto.mouse as mouse
import pywinauto.keyboard as keyboard

ACTION = "__ACTION__"
PARAMS = json.loads(base64.b64decode("__PARAMS_B64__").decode("utf-8"))
RESULT_MARKER = "__RESULT_MARKER__"
WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H = __WINDOW_X__, __WINDOW_Y__, __WINDOW_W__, __WINDOW_H__


def emit(result):
    print(RESULT_MARKER + json.dumps(result))


def find_place_window(place_name):
    title = place_name + " - Roblox Studio"
    try:
        app = Application(backend="uia").connect(title=title)
        return app.top_window()
    except Exception:
        return None


def find_home_window():
    candidates = []
    for w in Desktop(backend="uia").windows():
        try:
            if w.window_text() == "Roblox Studio":
                r = w.rectangle()
                candidates.append((r.width(), w))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def pin_window(win):
    try:
        win.move_window(x=WINDOW_X, y=WINDOW_Y, width=WINDOW_W, height=WINDOW_H)
    except Exception:
        pass
    win.set_focus()
    time.sleep(0.3)


def close_stray_home_windows(place_name, require_place_open=True):
    if require_place_open and find_place_window(place_name) is None:
        return 0
    closed = 0
    for w in Desktop(backend="uia").windows():
        try:
            if w.window_text() == "Roblox Studio":
                w.close()
                closed += 1
        except Exception:
            continue
    return closed


def dismiss_dialogs(rounds=2):
    for _ in range(rounds):
        keyboard.send_keys("{ESC}")
        time.sleep(0.2)


def do_status(params):
    place_name = params.get("place_name", "")
    win = find_place_window(place_name) if place_name else None
    home = find_home_window()
    return {
        "success": True,
        "place_open": win is not None,
        "home_screen_open": home is not None,
        "windows": [w.window_text() for w in Desktop(backend="uia").windows() if w.window_text()],
    }


def do_ensure_open(params):
    place_name = params.get("place_name", "")
    win = find_place_window(place_name)
    if win is not None:
        pin_window(win)
        closed = close_stray_home_windows(place_name)
        return {"success": True, "state": "already_open", "stray_windows_closed": closed}

    home = find_home_window()
    if home is None:
        return {
            "success": False,
            "state": "no_studio_window",
            "detail": "Neither the place nor the Studio home screen is open -- Studio "
                      "process itself may not be running. Cold-launch is not implemented "
                      "here yet, start Studio manually once and this will handle the rest.",
        }

    pin_window(home)
    fx, fy = 0.267, 0.611
    x = WINDOW_X + int(WINDOW_W * fx)
    y = WINDOW_Y + int(WINDOW_H * fy)
    mouse.click(button="left", coords=(x, y))
    time.sleep(3)
    win = find_place_window(place_name)
    if win is not None:
        pin_window(win)
        closed = close_stray_home_windows(place_name)
        return {"success": True, "state": "opened_via_recents_tile", "stray_windows_closed": closed}
    return {
        "success": False,
        "state": "click_did_not_open_place",
        "detail": "Clicked the first Recents tile but the place window never appeared -- "
                  "layout probably shifted, or it wasn't the first tile. Re-measure fx/fy.",
    }


def do_cleanup_stray_windows(params):
    place_name = params.get("place_name", "")
    closed = close_stray_home_windows(place_name, require_place_open=params.get("require_place_open", True))
    return {"success": True, "closed": closed}


def do_publish(params):
    place_name = params.get("place_name", "")
    win = find_place_window(place_name)
    if win is None:
        return {"success": False, "detail": "place not open, call ensure_open first"}
    pin_window(win)
    dismiss_dialogs()
    pin_window(win)

    mouse.click(button="left", coords=(WINDOW_X + 20, WINDOW_Y + 14))
    time.sleep(0.6)
    keyboard.send_keys("{DOWN 13}{ENTER}")
    time.sleep(1.0)
    dismiss_dialogs()
    return {"success": True, "detail": "Publish to Roblox triggered. Verify externally via "
                                        "Open Cloud updateTime -- this action cannot confirm "
                                        "the publish actually landed, only that the menu path "
                                        "was executed."}


def do_close_place(params):
    place_name = params.get("place_name", "")
    win = find_place_window(place_name)
    if win is None:
        return {"success": False, "detail": "place not open"}
    win.set_focus()
    time.sleep(0.3)
    keyboard.send_keys("^{F4}")
    time.sleep(1.0)
    still_open = find_place_window(place_name) is not None
    return {"success": not still_open, "detail": "closed" if not still_open else "close did not take effect"}


def do_dismiss_dialogs(params):
    dismiss_dialogs(rounds=params.get("rounds", 2))
    return {"success": True}


def do_screenshot(params):
    from PIL import ImageGrab
    place_name = params.get("place_name", "")
    win = find_place_window(place_name) or find_home_window()
    if win is None:
        return {"success": False, "detail": "no Studio window found"}
    pin_window(win)
    r = win.rectangle()
    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"success": True, "png_base64": b64, "width": img.width, "height": img.height}


ACTIONS = {
    "status": do_status,
    "ensure_open": do_ensure_open,
    "publish": do_publish,
    "close_place": do_close_place,
    "dismiss_dialogs": do_dismiss_dialogs,
    "screenshot": do_screenshot,
    "cleanup_stray_windows": do_cleanup_stray_windows,
}

try:
    handler = ACTIONS.get(ACTION)
    if handler is None:
        emit({"success": False, "detail": "unknown action " + repr(ACTION)})
    else:
        emit(handler(PARAMS))
except Exception as exc:
    emit({"success": False, "detail": "exception: " + repr(exc)})
'''


def _render_windows_script(action: str, params: dict) -> str:
    params_b64 = base64.b64encode(json.dumps(params).encode("utf-8")).decode("ascii")
    script = _WINDOWS_SCRIPT
    script = script.replace("__ACTION__", action)
    script = script.replace("__PARAMS_B64__", params_b64)
    script = script.replace("__RESULT_MARKER__", _RESULT_MARKER)
    script = script.replace("__WINDOW_X__", str(WINDOW_X))
    script = script.replace("__WINDOW_Y__", str(WINDOW_Y))
    script = script.replace("__WINDOW_W__", str(WINDOW_W))
    script = script.replace("__WINDOW_H__", str(WINDOW_H))
    return script


def _exec_remote(command: str, timeout: int = 60) -> tuple[str, str, int]:
    """POST the exec endpoint (see module docstring for the contract),
    drain the NDJSON stream, return (stdout, stderr, returncode)."""
    base_url = config.studio_exec_base_url()
    client_id = config.studio_exec_client_id()
    if not base_url or not client_id:
        raise RuntimeError(_NO_EXEC)

    url = f"{base_url}/api/clients/{client_id}/exec"
    body = json.dumps({"command": command, "timeout": timeout}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    returncode = -1
    with urllib.request.urlopen(req, timeout=timeout + 20) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line:
                continue
            item = json.loads(line)
            if item.get("done"):
                returncode = item.get("returncode", -1)
                break
            if item.get("stream") == "stderr":
                stderr_parts.append(item.get("data", ""))
            else:
                stdout_parts.append(item.get("data", ""))
    return "".join(stdout_parts), "".join(stderr_parts), returncode


def _run(action: str, params: dict, timeout: int = 60) -> dict:
    script = _render_windows_script(action, params)
    script_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    ps_command = (
        f'$b = [System.Convert]::FromBase64String("{script_b64}"); '
        f'$src = [System.Text.Encoding]::UTF8.GetString($b); '
        f'$src | python -'
    )
    try:
        stdout, stderr, returncode = _exec_remote(ps_command, timeout=timeout)
    except RuntimeError as exc:
        return {"success": False, "detail": str(exc)}
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        return {"success": False, "detail": f"exec endpoint unreachable: {exc}"}

    for line in reversed(stdout.splitlines()):
        if line.startswith(_RESULT_MARKER):
            try:
                result = json.loads(line[len(_RESULT_MARKER):])
            except json.JSONDecodeError:
                break
            result["_returncode"] = returncode
            return result

    return {
        "success": False,
        "detail": "no result marker found in remote output -- the script crashed before "
                  "reaching emit(), or exec itself failed",
        "_returncode": returncode,
        "_stdout": stdout[-2000:],
        "_stderr": stderr[-2000:],
    }


# ─── Public API ─────────────────────────────────────────────────────────

def status(place_name: str = DEFAULT_PLACE_NAME) -> dict:
    return _run("status", {"place_name": place_name})


def ensure_open(place_name: str = DEFAULT_PLACE_NAME) -> dict:
    return _run("ensure_open", {"place_name": place_name}, timeout=45)


def publish(place_name: str = DEFAULT_PLACE_NAME) -> dict:
    return _run("publish", {"place_name": place_name}, timeout=60)


def close_place(place_name: str = DEFAULT_PLACE_NAME) -> dict:
    return _run("close_place", {"place_name": place_name}, timeout=20)


def dismiss_dialogs(rounds: int = 2) -> dict:
    return _run("dismiss_dialogs", {"rounds": rounds}, timeout=15)


def screenshot(place_name: str = DEFAULT_PLACE_NAME) -> dict:
    return _run("screenshot", {"place_name": place_name}, timeout=30)


def cleanup_stray_windows(place_name: str = DEFAULT_PLACE_NAME, require_place_open: bool = True) -> dict:
    return _run("cleanup_stray_windows", {"place_name": place_name, "require_place_open": require_place_open}, timeout=20)


def force_shutdown_servers() -> dict:
    """Force every currently-running server for this universe to shut down
    via Roblox's Open Cloud "Publish Message" REST API (topic
    ``ForceShutdownOnPublish``) -- see ``VersionWatcher.server.lua`` in the
    aw-roblox game repo (not ported here, out of scope for this app) for
    the in-game listener. ``roblox_api_key``/``roblox_universe_id`` come
    from this app's config now, not a ``.env`` file on a shared checkout."""
    api_key = config.roblox_api_key()
    universe_id = config.universe_id()
    if not api_key:
        return {"success": False, "error": f"'{config.ROBLOX_API_KEY}' is not configured in this app's Settings"}
    body = json.dumps({"message": "publish"}).encode()
    req = urllib.request.Request(
        f"https://apis.roblox.com/messaging-service/v1/universes/{universe_id}/topics/{FORCE_SHUTDOWN_TOPIC}",
        data=body, method="POST",
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {"success": 200 <= resp.status < 300, "status_code": resp.status, "body": resp.read().decode()}
    except urllib.error.HTTPError as exc:
        return {"success": False, "status_code": exc.code, "body": exc.read().decode()}
    except urllib.error.URLError as exc:
        return {"success": False, "error": str(exc)}


def _get_universe_updated(universe_id: str) -> str | None:
    """Return the `updated` ISO timestamp Roblox reports for this universe.
    Public, unauthenticated endpoint -- no Open Cloud key needed, just the
    universe id. The only reliable signal a publish actually landed (see
    _publish_workflow_with_retry)."""
    req = urllib.request.Request(f"https://games.roblox.com/v1/games?universeIds={universe_id}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read()).get("data") or []
    return data[0].get("updated") if data else None


def _publish_workflow_with_retry(place_name: str, max_attempts: int = 3) -> dict:
    """publish_workflow() + a reliability retry cross-checked via Open Cloud.

    Known bug (documented in the aw-roblox skill): File -> Publish to
    Roblox can silently no-op roughly 1 in 3 calls -- no error, but the
    universe's `updated` timestamp never advances. Fix: close_place() +
    reopen + publish again releases the stuck session lock."""
    attempts = []
    universe_id = config.universe_id()
    before = _get_universe_updated(universe_id)

    for attempt_num in range(1, max_attempts + 1):
        if attempt_num == 1:
            r = dismiss_dialogs()
            r2 = ensure_open(place_name)
            r3 = publish(place_name) if r2.get("success") else {"success": False, "detail": "ensure_open failed"}
            step_result = {"success": r3.get("success", False),
                           "steps": [{"step": "dismiss_dialogs", **r}, {"step": "ensure_open", **r2}, {"step": "publish", **r3}]}
        else:
            close_r = close_place(place_name)
            open_r = ensure_open(place_name)
            publish_r = publish(place_name)
            step_result = {
                "success": publish_r.get("success", False),
                "steps": [
                    {"step": "close_place", **close_r},
                    {"step": "ensure_open", **open_r},
                    {"step": "publish", **publish_r},
                ],
            }

        time.sleep(3)  # give Open Cloud a moment to reflect the publish
        after = _get_universe_updated(universe_id)
        landed = bool(after) and after != before

        attempts.append({
            "attempt": attempt_num,
            "workflow_result": step_result,
            "updated_before": before,
            "updated_after": after,
            "landed": landed,
        })

        if landed:
            shutdown_r = force_shutdown_servers()
            return {"success": True, "landed": True, "attempts": attempts, "force_shutdown_servers": shutdown_r}

        before = after or before

    return {
        "success": False,
        "landed": False,
        "attempts": attempts,
        "detail": f"updateTime never advanced across {max_attempts} attempts -- "
                  "the Studio host may need a human look.",
    }


# ─── MCP tool handlers ──────────────────────────────────────────────────

def _status(args: dict) -> tuple[str, bool]:
    result = status(args.get("place_name", DEFAULT_PLACE_NAME))
    return json.dumps(result), not result.get("success", False)


def _ensure_open(args: dict) -> tuple[str, bool]:
    result = ensure_open(args.get("place_name", DEFAULT_PLACE_NAME))
    return json.dumps(result), not result.get("success", False)


def _publish(args: dict) -> tuple[str, bool]:
    result = publish(args.get("place_name", DEFAULT_PLACE_NAME))
    return json.dumps(result), not result.get("success", False)


def _close_place(args: dict) -> tuple[str, bool]:
    result = close_place(args.get("place_name", DEFAULT_PLACE_NAME))
    return json.dumps(result), not result.get("success", False)


def _dismiss_dialogs(args: dict) -> tuple[str, bool]:
    result = dismiss_dialogs(int(args.get("rounds", 2)))
    return json.dumps(result), not result.get("success", False)


def _screenshot(args: dict) -> tuple[str, bool]:
    result = screenshot(args.get("place_name", DEFAULT_PLACE_NAME))
    return json.dumps(result), not result.get("success", False)


def _cleanup_stray_windows(args: dict) -> tuple[str, bool]:
    result = cleanup_stray_windows(
        args.get("place_name", DEFAULT_PLACE_NAME),
        require_place_open=bool(args.get("require_place_open", True)),
    )
    return json.dumps(result), not result.get("success", False)


def _publish_workflow(args: dict) -> tuple[str, bool]:
    place_name = args.get("place_name", DEFAULT_PLACE_NAME)
    max_attempts = int(args.get("max_attempts", 3))
    result = _publish_workflow_with_retry(place_name, max_attempts=max_attempts)
    return json.dumps(result), not result.get("success", False)


_PLACE_NAME_PROP = {
    "place_name": {
        "type": "string",
        "description": f"Roblox Studio place window title (default '{DEFAULT_PLACE_NAME}').",
    },
}

TOOLS_SCHEMA = [
    {
        "name": "roblox_gui_status",
        "description": "Report whether the Roblox Studio place / home screen is currently open on the configured exec host.",
        "inputSchema": {"type": "object", "properties": _PLACE_NAME_PROP},
    },
    {
        "name": "roblox_gui_ensure_open",
        "description": (
            "Open the place in Roblox Studio if it isn't already. Best-effort: only "
            "handles 'Studio running, showing home screen' -- does not cold-launch Studio."
        ),
        "inputSchema": {"type": "object", "properties": _PLACE_NAME_PROP},
    },
    {
        "name": "roblox_gui_publish",
        "description": (
            "File -> Publish to Roblox on the currently-open place. Publishes the whole "
            "live Workspace (including manually-inserted assets), unlike the Open Cloud "
            "API pipeline which only publishes the Rojo-tracked source tree. Does NOT "
            "verify the publish landed -- prefer roblox_gui_publish_workflow, which does."
        ),
        "inputSchema": {"type": "object", "properties": _PLACE_NAME_PROP},
    },
    {
        "name": "roblox_gui_close_place",
        "description": "Ctrl+F4 -- releases a stuck publish lock. Follow with roblox_gui_ensure_open to get back in.",
        "inputSchema": {"type": "object", "properties": _PLACE_NAME_PROP},
    },
    {
        "name": "roblox_gui_dismiss_dialogs",
        "description": "Send Escape a few times to clear an unexpected modal (version-notes prompt, migration notices, etc). Safe no-op if nothing is open.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rounds": {"type": "integer", "description": "How many times to send Escape (default 2)."},
            },
        },
    },
    {
        "name": "roblox_gui_screenshot",
        "description": "Grab a PNG of the pinned Studio window, base64-encoded inline in the result (png_base64).",
        "inputSchema": {"type": "object", "properties": _PLACE_NAME_PROP},
    },
    {
        "name": "roblox_gui_cleanup_stray_windows",
        "description": (
            "Close every un-suffixed 'Roblox Studio' home/launcher window left behind on "
            "the exec host. close_place() (Ctrl+F4) shows the launcher instead of exiting "
            "the process, and each close+reopen cycle opens a NEW launcher window instead "
            "of reusing the last one -- these accumulate across repeated publish/retry "
            "runs. By default only closes them once the actual place window is confirmed "
            "open, so this can never strand you with nothing open; pass "
            "require_place_open=false to force-clean regardless."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_PLACE_NAME_PROP,
                "require_place_open": {
                    "type": "boolean",
                    "description": "Only close home windows if the place is confirmed open (default true).",
                },
            },
        },
    },
    {
        "name": "roblox_gui_publish_workflow",
        "description": (
            "Composite: dismiss dialogs, ensure the place is open, publish, then "
            "cross-check via the public games.roblox.com `updated` timestamp for the "
            "universe -- Studio's own success report can't be trusted alone, roughly "
            "1 in 3 publishes silently no-op (documented gotcha). If `updated` didn't "
            "move, close_place() + ensure_open() + publish() again (releases the stuck "
            "session lock that's the known root cause), up to max_attempts total tries. "
            "Returns every attempt's raw results plus the before/after timestamps, not "
            "just a final bool -- inspect `landed` for ground truth."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_PLACE_NAME_PROP,
                "max_attempts": {
                    "type": "integer",
                    "description": "How many publish attempts before giving up (default 3).",
                },
            },
        },
    },
]

DISPATCH = {
    "roblox_gui_status": _status,
    "roblox_gui_ensure_open": _ensure_open,
    "roblox_gui_publish": _publish,
    "roblox_gui_close_place": _close_place,
    "roblox_gui_dismiss_dialogs": _dismiss_dialogs,
    "roblox_gui_screenshot": _screenshot,
    "roblox_gui_cleanup_stray_windows": _cleanup_stray_windows,
    "roblox_gui_publish_workflow": _publish_workflow,
}
