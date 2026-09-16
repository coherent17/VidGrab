"""Offline/online detection with a captive-portal probe (stdlib only)."""

from __future__ import annotations

import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

# Public DNS resolvers used for the raw TCP reachability check.
_TCP_HOSTS: list[tuple[str, int]] = [
    ("1.1.1.1", 53),
    ("8.8.8.8", 53),
    ("208.67.222.222", 53),
]

# A dedicated endpoint that answers 204 No Content when real internet traffic
# flows through (catches captive portals that block arbitrary hosts).
_PROBE_URL = "http://clients3.google.com/generate_204"
_PROBE_TIMEOUT = 4.0


@dataclass(frozen=True)
class ConnectionStatus:
    online: bool
    reason: str


def _reachable(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _tcp_online(timeout: float) -> bool:
    return any(
        _reachable(host, port, timeout) for host, port in _TCP_HOSTS
    )


def _gateway_online(timeout: float) -> bool:
    """True when a 204 gateway endpoint answers => internet (not captive)."""
    try:
        with urllib.request.urlopen(_PROBE_URL, timeout=timeout) as resp:
            return resp.status == 204
    except Exception:  # noqa: BLE001 - any failure means offline/captive
        return False


def check_internet(timeout: float = _PROBE_TIMEOUT) -> ConnectionStatus:
    """
    Determine whether the machine has real internet access.

    *down* => TCP to public resolvers fails (no network / offline).
    *up*   => gateway 204 answered (full internet access).
    *walled* => TCP works but the 204 gateway does not (captive portal,
    DNS blocking, or proxy); treated as offline.
    """
    if not _tcp_online(timeout):
        return ConnectionStatus(False, "no route to the internet")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_gateway_online, timeout)
        try:
            gateway = future.result(timeout=timeout + 1.0)
        except TimeoutError:
            gateway = False

    if gateway:
        return ConnectionStatus(True, "online")
    return ConnectionStatus(False, "captive portal or restricted network")