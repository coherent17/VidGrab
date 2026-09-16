"""Tests for the stdlib internet/captive-portal probe (all mocked)."""

from __future__ import annotations

from vidgrab import network


def test_offline_when_no_tcp_path(monkeypatch) -> None:
    monkeypatch.setattr(network, "_tcp_online", lambda timeout: False)
    status = network.check_internet()
    assert status.online is False
    assert "internet" in status.reason.lower() or "route" in status.reason.lower()


def test_online_when_tcp_and_gateway_ok(monkeypatch) -> None:
    monkeypatch.setattr(network, "_tcp_online", lambda timeout: True)
    monkeypatch.setattr(network, "_gateway_online", lambda timeout: True)
    status = network.check_internet()
    assert status.online is True


def test_captive_portal_is_treated_offline(monkeypatch) -> None:
    monkeypatch.setattr(network, "_tcp_online", lambda timeout: True)
    monkeypatch.setattr(network, "_gateway_online", lambda timeout: False)
    status = network.check_internet()
    assert status.online is False
    assert "captive" in status.reason.lower()


def test_gateway_204_counts_as_online(monkeypatch) -> None:
    class Resp:
        status = 204

    class UrlOpen:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> Resp:
            return Resp()

        def __exit__(self, *args) -> None:
            return None

    monkeypatch.setattr(network.urllib.request, "urlopen", UrlOpen)
    assert network._gateway_online(1.0) is True


def test_gateway_failure_is_offline(monkeypatch) -> None:
    class Boom:
        def __init__(self, *args, **kwargs) -> None:
            raise OSError("no dns")

    monkeypatch.setattr(network.urllib.request, "urlopen", Boom)
    assert network._gateway_online(1.0) is False