#!/usr/bin/env python3
# This is AI generated code
"""Run a single Home Assistant websocket command from the HA host.

A dev-deploy verification helper. Some commands -- chiefly
``persistent_notification/get`` -- have no REST equivalent, so
verifying notification baselines needs a websocket client.

Runs on the HA host (over SSH), not the dev machine: on hosts whose
inbound path strips the ``Authorization`` header (a reverse proxy or
a Tailscale/LAN ingress in front of port 8123), an authenticated call
from the dev machine returns ``401`` regardless of token validity,
while the same token reaches HA core intact over the internal
supervisor network. The host's system ``python3`` is expected to have
``websockets`` importable; ``uv`` is not assumed present, so this is
plain Python with no PEP 723 block.

Usage
-----

    HA_TOKEN=... ha_ws_fetch.py [command] [--url WS] [--token-file F] \
        [--timeout SECONDS]

``command`` defaults to ``persistent_notification/get``. The result of
the command is printed to stdout as indented JSON. The token comes
from ``--token-file`` if given, else the ``HA_TOKEN`` environment
variable. Exits non-zero (with a message on stderr) on auth rejection,
a failed command, or a connection failure (refused / closed / timed
out).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_URL = "ws://homeassistant:8123/api/websocket"
DEFAULT_COMMAND = "persistent_notification/get"
DEFAULT_TIMEOUT = 30.0
_COMMAND_ID = 1


class WebsocketError(RuntimeError):
    """The HA websocket rejected authentication or a command."""


async def _exchange(ws: Any, token: str, command: str) -> Any:
    """Authenticate then run one command over an open ws; return its result.

    ``ws`` is any object exposing awaitable ``send(str)`` and
    ``recv() -> str`` -- the live ``websockets`` client connection or a
    test double. Follows HA's websocket auth handshake (``auth_required``
    -> ``auth`` -> ``auth_ok``) before issuing the command and waiting
    for the matching ``result`` frame.
    """
    hello = json.loads(await ws.recv())
    if hello.get("type") != "auth_required":
        raise WebsocketError(f"expected auth_required, got {hello!r}")

    await ws.send(json.dumps({"type": "auth", "access_token": token}))
    ack = json.loads(await ws.recv())
    if ack.get("type") != "auth_ok":
        raise WebsocketError(f"authentication rejected: {ack!r}")

    await ws.send(json.dumps({"id": _COMMAND_ID, "type": command}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == _COMMAND_ID and msg.get("type") == "result":
            if not msg.get("success", False):
                raise WebsocketError(f"command {command!r} failed: {msg!r}")
            return msg.get("result")


async def fetch(
    url: str, token: str, command: str, timeout: float = DEFAULT_TIMEOUT
) -> Any:
    """Open a websocket to ``url`` and run a single command.

    Connection-level failures (refused, closed mid-exchange, or no
    response within ``timeout`` seconds) are re-raised as
    ``WebsocketError`` so callers see one failure type and the CLI's
    documented exit-code contract holds. ``WebsocketError`` raised by
    ``_exchange`` (auth / command rejection) propagates unchanged.
    """
    from websockets.asyncio.client import connect
    from websockets.exceptions import WebSocketException

    try:
        async with asyncio.timeout(timeout):
            async with connect(url, max_size=None) as ws:
                return await _exchange(ws, token, command)
    except (OSError, WebSocketException) as exc:
        raise WebsocketError(
            f"websocket exchange with {url} failed: {exc}"
        ) from exc


def _read_token(token_file: str | None) -> str:
    if token_file:
        token = Path(token_file).read_text().strip()
    else:
        token = os.environ.get("HA_TOKEN", "").strip()
    if not token:
        raise WebsocketError(
            "no token: set HA_TOKEN in the environment or pass --token-file"
        )
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one HA websocket command and print its JSON result."
    )
    parser.add_argument(
        "command",
        nargs="?",
        default=DEFAULT_COMMAND,
        help=f"websocket command type (default: {DEFAULT_COMMAND})",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"websocket URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--token-file",
        help="read the access token from this file instead of $HA_TOKEN",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds to wait for the exchange (default: {DEFAULT_TIMEOUT})",
    )
    args = parser.parse_args(argv)

    try:
        token = _read_token(args.token_file)
        result = asyncio.run(
            fetch(args.url, token, args.command, timeout=args.timeout)
        )
    except WebsocketError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
