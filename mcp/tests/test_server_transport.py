"""Tests for how ``main()`` starts each transport.

``mcp`` 2.0 moved ``host``/``port`` off the server constructor and onto
``run()``, and replaced the single ``mount_path`` with one path per endpoint.
These tests pin that wiring so a silent bind on the wrong interface, or a lost
mount path, fails here.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from supoclip_mcp import server


@pytest.fixture
def run_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Record ``mcp.run()`` calls instead of starting a server."""
    calls: list[dict] = []

    def fake_run(transport: str = "stdio", **kwargs: object) -> None:
        calls.append({"transport": transport, **kwargs})

    monkeypatch.setattr(server.mcp, "run", fake_run)
    return calls


def _with(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    monkeypatch.setattr(server, "SETTINGS", replace(server.SETTINGS, **overrides))


def test_stdio_gets_no_network_options(
    monkeypatch: pytest.MonkeyPatch, run_calls: list[dict]
) -> None:
    _with(monkeypatch, mcp_transport="stdio")

    server.main()

    assert run_calls == [{"transport": "stdio"}]


def test_sse_binds_the_configured_host_and_port(
    monkeypatch: pytest.MonkeyPatch, run_calls: list[dict]
) -> None:
    _with(monkeypatch, mcp_transport="sse", mcp_host="0.0.0.0", mcp_port=9100)

    server.main()

    assert run_calls == [{"transport": "sse", "host": "0.0.0.0", "port": 9100}]


def test_streamable_http_binds_the_configured_host_and_port(
    monkeypatch: pytest.MonkeyPatch, run_calls: list[dict]
) -> None:
    _with(monkeypatch, mcp_transport="streamable-http", mcp_host="0.0.0.0", mcp_port=9100)

    server.main()

    assert run_calls == [{"transport": "streamable-http", "host": "0.0.0.0", "port": 9100}]


def test_mount_path_becomes_explicit_sse_paths(
    monkeypatch: pytest.MonkeyPatch, run_calls: list[dict]
) -> None:
    _with(monkeypatch, mcp_transport="sse", mcp_mount_path="/supoclip")

    server.main()

    assert run_calls[0]["sse_path"] == "/supoclip/sse"
    assert run_calls[0]["message_path"] == "/supoclip/messages/"


@pytest.mark.parametrize("mount_path", ["/", "", "///"])
def test_root_mount_path_keeps_the_defaults(mount_path: str) -> None:
    """A root mount path must not restate the default endpoints."""
    assert server._sse_paths(mount_path) == {}
