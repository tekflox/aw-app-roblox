"""Minimal client for aw-backend's ``/api/workspaces/{slug}/remote-host*``
routes — the exec transport ``mcp/roblox_gui.py`` uses to reach whatever
machine has Roblox Studio open.

Deliberately a small, self-contained copy of the relevant slice of
``aw-app-remote-host-cli/remote_host_cli_app/client.py`` rather than a
cross-app import: apps here don't import each other's Python packages (the
established pattern for cross-app reuse is a loopback REST call, see
``genie_kanban.py``'s call into aw-app-notion) and this app's container has
no dependency edge on that one's package. Same auth story though: this
workspace's own ``AW_WORKSPACE_HOST_TOKEN`` (minted by the aw-remote-host
``/link`` handshake), resolved from ``os.environ`` first, then
``<AW_WORKSPACE_HOME>/.env`` — the aw-app-remote-host-cli app publishes it
there on every activate, and both apps run in the same in-process
container, so it's already on disk by the time this app needs it.
"""
from __future__ import annotations

import os

import httpx

DEFAULT_BACKEND_URL = "http://127.0.0.1:9025"
DEFAULT_WORKSPACE_CONTAINER_DIR = "/opt/aw-workspace"


def _default_env_file() -> str:
    home = os.environ.get("AW_WORKSPACE_HOME") or os.path.join(
        os.environ.get("AW_WORKSPACE_CONTAINER_DIR", DEFAULT_WORKSPACE_CONTAINER_DIR), ".aw-workspace"
    )
    return os.path.join(home, ".env")


def _read_env_file_value(key: str) -> str | None:
    path = os.environ.get("AW_WORKSPACE_ENV_FILE") or _default_env_file()
    prefix = f"{key}="
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(prefix):
                    return line[len(prefix):].strip() or None
    except FileNotFoundError:
        return None
    return None


def _resolve(key: str, default: str = "") -> str:
    return os.environ.get(key) or _read_env_file_value(key) or default


class NotConfigured(RuntimeError):
    """AW_BACKEND_URL / AW_WORKSPACE / AW_WORKSPACE_HOST_TOKEN aren't all
    present — this workspace hasn't completed the aw-remote-host /link
    handshake yet."""


class RemoteHostError(RuntimeError):
    """Non-2xx response from aw-backend, message parsed from the body."""


class RemoteHostClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self.backend_url = _resolve("AW_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")
        self.workspace = _resolve("AW_WORKSPACE")
        self.token = _resolve("AW_WORKSPACE_HOST_TOKEN")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.backend_url and self.workspace and self.token)

    def _require_configured(self) -> None:
        if not self.configured:
            raise NotConfigured(
                "AW_BACKEND_URL, AW_WORKSPACE and AW_WORKSPACE_HOST_TOKEN are not all "
                "available on this host yet -- the aw-remote-host /link handshake may "
                "not have completed."
            )

    def _base(self, host_id: str | None) -> str:
        if host_id:
            return f"{self.backend_url}/api/workspaces/{self.workspace}/remote-hosts/{host_id}"
        return f"{self.backend_url}/api/workspaces/{self.workspace}/remote-host"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, path: str, *, json_body: dict | None = None,
                 params: dict | None = None, timeout: float | None = None,
                 host_id: str | None = None) -> dict:
        self._require_configured()
        url = f"{self._base(host_id)}{path}"
        try:
            resp = httpx.request(
                method, url, json=json_body, params=params, headers=self._headers(),
                timeout=timeout if timeout is not None else self.timeout,
            )
        except httpx.HTTPError as e:
            raise RemoteHostError(str(e)) from e
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            raise RemoteHostError(data.get("error") or data.get("detail") or f"HTTP {resp.status_code}")
        return data

    def list_account_hosts(self) -> dict:
        """``GET /api/workspaces/{slug}/remote-hosts`` — every host linked
        across this account, not just this workspace's own."""
        self._require_configured()
        url = f"{self.backend_url}/api/workspaces/{self.workspace}/remote-hosts"
        try:
            resp = httpx.request("GET", url, headers=self._headers(), timeout=self.timeout)
        except httpx.HTTPError as e:
            raise RemoteHostError(str(e)) from e
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            raise RemoteHostError(data.get("error") or data.get("detail") or f"HTTP {resp.status_code}")
        return data

    def exec_start(self, command: str, host_id: str | None, timeout_s: float | None = None) -> dict:
        body: dict = {"command": command}
        if timeout_s is not None:
            body["timeout_s"] = timeout_s
        return self._request("POST", "/exec", json_body=body, host_id=host_id)

    def exec_wait(self, job_id: str, host_id: str | None, timeout_s: float | None = None) -> dict:
        body: dict = {}
        if timeout_s is not None:
            body["timeout_s"] = timeout_s
        wait_budget = float(timeout_s) if timeout_s else 30.0
        return self._request("POST", f"/exec/{job_id}/wait", json_body=body,
                              timeout=wait_budget + 15.0, host_id=host_id)

    def run(self, command: str, host_id: str | None, timeout_s: float = 60.0) -> tuple[str, str, int]:
        """``exec_start`` + ``exec_wait`` in one call, returning
        ``(stdout, stderr, returncode)`` — the same shape
        ``mcp/roblox_gui.py``'s old NDJSON transport returned, so it's a
        drop-in replacement there."""
        started = self.exec_start(command, host_id, timeout_s=timeout_s)
        job_id = started.get("job_id")
        if not job_id:
            raise RemoteHostError(f"exec_start did not return a job_id: {started}")
        result = self.exec_wait(job_id, host_id, timeout_s=timeout_s)
        return result.get("stdout") or "", result.get("stderr") or "", result.get("exit_code", -1)


def resolve_host_ref(client: RemoteHostClient, ref: str) -> str:
    """Turn a host id, workspace slug, or hostname into a host id — same
    matching rules as aw-app-remote-host-cli's ``hosts.resolve_host_ref``
    (id first, then case-insensitive slug/hostname; ambiguous non-id matches
    fall back to whichever one is actually connected)."""
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("resolve_host_ref needs a non-empty reference")
    if len(ref) == 16 and all(c in "0123456789abcdef" for c in ref):
        return ref

    hosts = (client.list_account_hosts() or {}).get("hosts") or []
    needle = ref.casefold()
    matches = [h for h in hosts
               if (h.get("workspace_slug") or "").casefold() == needle
               or (h.get("hostname") or "").casefold() == needle]

    if not matches:
        known = ", ".join(f"{h.get('id')} ({h.get('hostname')})" for h in hosts) or "(none)"
        raise RemoteHostError(f"no host matching {ref!r}. Known hosts: {known}")

    if len(matches) > 1:
        connected = [h for h in matches if h.get("connected")]
        if len(connected) == 1:
            matches = connected
        else:
            listed = ", ".join(f"{h.get('id')} ({h.get('hostname')})" for h in matches)
            raise RemoteHostError(f"{ref!r} matches {len(matches)} hosts, name one by id: {listed}")

    return matches[0]["id"]
