#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "pytest-cov",
# ]
# ///
# This is AI generated code
"""Tests for scripts/ha_ws_fetch.py.

Exercises the websocket auth + command protocol (``_exchange``) with a
scripted fake connection -- no live HA, no ``websockets`` dependency in
the test env -- plus ``main``'s token resolution and exit codes.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parent.parent

# ha_ws_fetch is a bare script, imported off a runtime sys.path entry
# the way the other script tests reach render_docs / zwave_network_info.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ha_ws_fetch  # noqa: E402

AUTH_REQUIRED = json.dumps({"type": "auth_required", "ha_version": "x"})
AUTH_OK = json.dumps({"type": "auth_ok"})


class FakeWs:
    """Scripted stand-in for a websockets client connection.

    ``recv`` returns the queued frames in order; ``send`` records the
    payloads the code under test transmits so the handshake + command
    framing can be asserted.
    """

    def __init__(self, frames: list[str]) -> None:
        self._frames = list(frames)
        self.sent: list[str] = []

    async def recv(self) -> str:
        return self._frames.pop(0)

    async def send(self, payload: str) -> None:
        self.sent.append(payload)


def _result_frame(*, success: bool = True, result: Any = None) -> str:
    frame: dict[str, Any] = {"id": 1, "type": "result", "success": success}
    if success:
        frame["result"] = result
    else:
        frame["error"] = {"code": "unknown_command", "message": "nope"}
    return json.dumps(frame)


# ---- _exchange protocol ---------------------------------------


def test_exchange_happy_path() -> None:
    payload = [{"notification_id": "x", "message": "m"}]
    ws = FakeWs([AUTH_REQUIRED, AUTH_OK, _result_frame(result=payload)])

    out = asyncio.run(
        ha_ws_fetch._exchange(ws, "tok", "persistent_notification/get")
    )

    assert out == payload
    sent = [json.loads(s) for s in ws.sent]
    assert sent[0] == {"type": "auth", "access_token": "tok"}
    assert sent[1] == {"id": 1, "type": "persistent_notification/get"}


def test_exchange_waits_for_matching_result() -> None:
    # An unrelated event frame ahead of the command result must be
    # skipped, not mistaken for the answer.
    event = json.dumps({"id": 9, "type": "event", "event": {}})
    ws = FakeWs([AUTH_REQUIRED, AUTH_OK, event, _result_frame(result=42)])

    out = asyncio.run(ha_ws_fetch._exchange(ws, "tok", "get_config"))

    assert out == 42


def test_exchange_rejects_missing_auth_required() -> None:
    ws = FakeWs([AUTH_OK])
    with pytest.raises(ha_ws_fetch.WebsocketError, match="auth_required"):
        asyncio.run(ha_ws_fetch._exchange(ws, "tok", "get_config"))


def test_exchange_auth_invalid() -> None:
    bad = json.dumps({"type": "auth_invalid", "message": "bad token"})
    ws = FakeWs([AUTH_REQUIRED, bad])
    with pytest.raises(ha_ws_fetch.WebsocketError, match="rejected"):
        asyncio.run(ha_ws_fetch._exchange(ws, "tok", "get_config"))


def test_exchange_command_failure() -> None:
    ws = FakeWs([AUTH_REQUIRED, AUTH_OK, _result_frame(success=False)])
    with pytest.raises(ha_ws_fetch.WebsocketError, match="failed"):
        asyncio.run(ha_ws_fetch._exchange(ws, "tok", "bogus/command"))


# ---- fetch connection handling --------------------------------


def _install_fake_websockets(
    monkeypatch: pytest.MonkeyPatch, connect_error: Exception
) -> None:
    """Inject a fake ``websockets`` whose ``connect`` raises an error.

    Lets ``fetch`` run without the real library (absent from the test
    env): its lazy ``from websockets...`` imports resolve to these
    stubs.
    """
    client_mod = types.ModuleType("websockets.asyncio.client")

    def connect(*_args: Any, **_kwargs: Any) -> Any:
        raise connect_error

    client_mod.connect = connect  # type: ignore[attr-defined]

    exc_mod = types.ModuleType("websockets.exceptions")
    exc_mod.WebSocketException = type(  # type: ignore[attr-defined]
        "WebSocketException", (Exception,), {}
    )

    fakes = {
        "websockets": types.ModuleType("websockets"),
        "websockets.asyncio": types.ModuleType("websockets.asyncio"),
        "websockets.asyncio.client": client_mod,
        "websockets.exceptions": exc_mod,
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_fetch_wraps_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_websockets(monkeypatch, ConnectionRefusedError("refused"))
    with pytest.raises(ha_ws_fetch.WebsocketError, match="failed"):
        asyncio.run(ha_ws_fetch.fetch("ws://x", "tok", "get_config"))


# ---- token resolution -----------------------------------------


def test_read_token_from_file(tmp_path: Path) -> None:
    token_file = tmp_path / "tok"
    token_file.write_text("  secret-token\n")
    assert ha_ws_fetch._read_token(str(token_file)) == "secret-token"


def test_read_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HA_TOKEN", "env-token\n")
    assert ha_ws_fetch._read_token(None) == "env-token"


def test_read_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HA_TOKEN", raising=False)
    with pytest.raises(ha_ws_fetch.WebsocketError, match="no token"):
        ha_ws_fetch._read_token(None)


# ---- main exit codes ------------------------------------------


def test_main_prints_json_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HA_TOKEN", "tok")

    async def fake_fetch(
        _url: str, _token: str, command: str, **_kwargs: Any
    ) -> Any:
        assert command == "get_config"
        return {"version": "2026.5.3"}

    monkeypatch.setattr(ha_ws_fetch, "fetch", fake_fetch)

    rc = ha_ws_fetch.main(["get_config"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"version": "2026.5.3"}


def test_main_auth_error_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HA_TOKEN", "tok")

    async def fake_fetch(
        _url: str, _token: str, _command: str, **_kwargs: Any
    ) -> Any:
        raise ha_ws_fetch.WebsocketError("authentication rejected")

    monkeypatch.setattr(ha_ws_fetch, "fetch", fake_fetch)

    rc = ha_ws_fetch.main([])

    assert rc == 1
    assert "rejected" in capsys.readouterr().err


def test_main_missing_token_returns_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HA_TOKEN", raising=False)
    assert ha_ws_fetch.main([]) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
