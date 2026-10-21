"""Keep the unit suite off the real network.

Unit tests run with placeholder credentials (SUPABASE_URL=http://127.0.0.1:9,
dummy provider keys). A test that forgets to mock a client would otherwise
send real requests to Recall/Gemini/Firecrawl/etc. with those keys — slow,
flaky, and leaking traffic to third parties.

`install()` patches socket name resolution and connects so any non-loopback
destination fails immediately with ConnectionRefusedError — the same failure
the suite already gets from the dummy loopback hosts — and records the attempt.
conftest.py then fails the offending test even when the code under test caught
the error, so a missing mock cannot pass silently. Mark tests that really need
the network with @pytest.mark.network.

Opt out with RUN_NETWORK_TESTS=1 (or SMOKE=1 for the staging smoke suite).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any

_LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "testserver", ""}

_attempts: list[tuple[str, str]] = []
_current_test: list[str] = ["<collection>"]


def network_allowed() -> bool:
    return os.getenv("RUN_NETWORK_TESTS") == "1" or os.getenv("SMOKE") == "1"


def _is_loopback(host: Any) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode(errors="ignore")
    host = str(host).strip("[]").lower()
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


class ExternalNetworkBlocked(ConnectionRefusedError):
    """Raised when a unit test tries to reach a non-loopback host."""


def _block(host: Any) -> None:
    _attempts.append((_current_test[0], str(host)))
    raise ExternalNetworkBlocked(
        f"unit tests may not reach external host {host!r}; mock the client "
        "(set RUN_NETWORK_TESTS=1 to allow)"
    )


def install() -> None:
    if network_allowed():
        return

    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            _block(host)
        return real_getaddrinfo(host, *args, **kwargs)

    def _check_address(sock: socket.socket, address: Any) -> None:
        if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
            if not _is_loopback(address[0]):
                _block(address[0])

    def guarded_connect(self, address):
        _check_address(self, address)
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        _check_address(self, address)
        return real_connect_ex(self, address)

    socket.getaddrinfo = guarded_getaddrinfo
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex


def set_current_test(nodeid: str) -> None:
    _current_test[0] = nodeid


def blocked_attempts() -> list[tuple[str, str]]:
    return list(_attempts)


def take_attempts(nodeid: str) -> list[str]:
    """Return and forget the blocked hosts recorded for one test."""
    hosts = [host for test, host in _attempts if test == nodeid]
    _attempts[:] = [(test, host) for test, host in _attempts if test != nodeid]
    return hosts
