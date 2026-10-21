"""The unit-test network guard blocks external hosts and attributes attempts."""

import socket

import pytest

from tests import _network_guard


def test_loopback_hosts_are_allowed():
    for host in ("127.0.0.1", "::1", "[::1]", "localhost", "testserver", None, b"127.0.0.1"):
        assert _network_guard._is_loopback(host)


def test_external_hosts_are_not_loopback():
    for host in ("api.openai.com", "8.8.8.8", "10.0.0.1"):
        assert not _network_guard._is_loopback(host)


@pytest.mark.skipif(_network_guard.network_allowed(), reason="guard disabled")
def test_external_resolution_raises_and_is_attributed(request):
    with pytest.raises(_network_guard.ExternalNetworkBlocked):
        socket.getaddrinfo("example.invalid", 443)
    # Consume the attempt so this deliberate probe does not fail the test.
    assert _network_guard.take_attempts(request.node.nodeid) == ["example.invalid"]
    assert _network_guard.take_attempts(request.node.nodeid) == []
