#!/usr/bin/env python3
# This is AI generated code
# Note: this file intentionally does not use the repo-standard
# PEP 723 + uv shebang (see DEVELOPMENT.md "Shebangs"). The
# Home Assistant host this ships to doesn't carry uv, so the
# script bootstraps its own venv at first run instead (see
# bootstrap_venv / reexec_in_venv below).
"""zwavectl: Z-Wave network and parameter-manager views, from the HA host."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypedDict, cast

HA_CONFIG_YAML = pathlib.Path("/config/configuration.yaml")
DEFAULT_RECORDER_KEEP_DAYS = 10  # HA built-in default when unset

_HELP_EPILOG_TEMPLATE = """\
Columns -- HA-derived
--------------------
  device          HA device friendly name.
  location        HA area assigned to the device.
  status          Node status as reported by zwave_js (alive, asleep, dead,
                  etc.). Sourced from the HA ``*_node_status`` sensor.
  last-seen       Compact relative age since this node was last heard from:
                  "5m", "3h", "2d". Derived from the HA ``*_last_seen`` sensor.
  battery         Battery level as a percentage. "-" for line-powered nodes.
  timeouts        Number of timed-out responses.

Columns -- HA-derived, with history
----------------------------------
  These columns respect --days: each cell becomes a space-separated list
  of "--days + 1" values, newest first ([latest, -1d, -2d, ...]).
  --days 0 collapses them to scalars. Sort targets the latest value.

  ss              Signal strength in dBm. See the Signal Strength section
                  below for the protocol-aware color thresholds.
  ss-quality      Protocol-aware bucket for ss: "good" / "fair" / "poor".
                  Colored the same as ss. Handy for scanning signal health
                  without comparing Mesh and LR numbers in your head.
  rtt             Round-trip time (ms).
  rx, tx          Successful commands received from / transmitted to this node.
  rx-drop,        Commands dropped on receive / transmit.
  tx-drop
  rx-drop-rate,   Drop fraction: drops / (drops + success), shown as
  tx-drop-rate    an integer percent (unit in the header). Colored green
                  (<1%), yellow (1-5%), red (>5%). "-" when the node has
                  no activity to compute a rate from.

Columns -- Z-Wave network
------------------------
  node            Z-Wave node ID.
  protocol        "Mesh" (Classic Z-Wave) or "LR" (Z-Wave Long Range). Matches
                  the "Protocol" column in the zwave-js-ui web UI.
  priority-route  Outbound (controller -> node) priority route, as set by the
                  zwave_route_manager automation. Shows the repeater's device
                  name, or "-" if unset.
  suc-route       Inbound (node -> controller) SUC return route. Same format
                  as priority-route. Differences from priority-route expose
                  direction-asymmetric state (e.g. outbound applied but return
                  still pending for a sleepy node).
  power           "Mains" (always-listening) or "Battery" (FLiRS / sleepy).
  route-speed     Actual rate of the current last working route ("9.6k",
                  "40k", "100k", "LR"). Different from max-speed -- surfaces
                  nodes that silently negotiate down.
  max-speed       Advertised max data rate ("9.6k" / "40k" / "100k"). Pair
                  with route-speed to spot under-utilized links.
  neighbors       Mesh neighbor node IDs. Example: "1 13 17 47 50 52".
                  "none" if the node reports no neighbors.
  manufacturer    Device manufacturer label (e.g. "Kwikset", "Aeotec Ltd.").
  product         Product description / marketing name.
  product-code    Manufacturer's product label / SKU (e.g. "HC620", "ZWA045").
  role            Z-Wave Plus role type (e.g. "AlwaysOn",
                  "SleepingReporting", "SleepingListening", "CentralCtrl").
  security        Highest security class in use (e.g. "S2_AccessControl",
                  "S2_Authenticated", "None").
  beaming         "yes" / "no" -- whether the node supports beaming (a Z-Wave
                  mechanism for reaching FLiRS nodes).
  firmware-dev    Device firmware version (e.g. "v7.20.0").
  firmware-sdk    Z-Wave SDK / chipset version (e.g. "v7.13.8").
  update          Firmware update availability: "no" or "yes (v<ver>)".
  plus            Z-Wave Plus version, "v1" / "v2" / "no".
  interview       zwave_js interview stage: typically "Complete". Non-Complete
                  values ("ProtocolInfo", "NodeInfo", "CommandClasses",
                  "OverwriteConfig") indicate an in-progress or stuck
                  interview.

Columns -- Aliases
-----------------
  Aliases are shortcuts for --cols only (not valid in --sort). They
  expand in place; duplicates are dropped.

  all             Every column.
{aliases_block}

Signal Strength
---------------
  ss values are the Z-Wave RSSI reported by the controller, in dBm.
  Higher (less negative) is stronger. Thresholds differ by protocol:
  Z-Wave LR has a higher TX-power ceiling (+14 dBm vs 0 dBm) and uses
  DSSS + Forward Error Correction, so it stays reliable ~15 dB below
  where Classic Mesh starts to fail.

  Classic Mesh:
    > -70 dBm        green    good     -- reliable link
    -70 to -85       yellow   fair     -- usable, margin is thin
    < -85 dBm        red      poor     -- retries and timeouts likely

  Z-Wave Long Range:
    > -80 dBm        green    good
    -80 to -100      yellow   fair
    < -100 dBm       red      poor

  ss and ss-quality both honor these thresholds. ss shows raw dBm with
  the threshold color; ss-quality shows the bucket label directly so
  you can compare Mesh and LR nodes side by side without mental
  conversion. ``--sort ss-quality`` lists the worst (poor) nodes first.

  Practical rule: a node sitting below poor on its own protocol row for
  multiple days is a candidate for a repeater (Mesh) or a relocation
  closer to the controller (LR). A single bad reading is often just
  transient interference.

RX/TX counters
--------------
  All counters come from zwave-js's ``NodeStatistics``, which is the
  *controller's* observation of traffic to and from the node:
    - RX = the controller received a frame from the node.
    - TX = the controller sent a frame to the node.
  Node-side activity isn't directly observable here.

  Important: lost-in-transit frames are unobservable. A frame that
  never reaches the controller, or an ACK that never comes back,
  looks identical to silence. Not all packet loss shows up in these
  counters.

  rx              Frames the controller successfully received and
                  decoded from the node.
  tx              Frames the controller successfully sent to the node
                  (got back a MAC-layer ACK within the retry budget).

  rx-drop         Frames that arrived at the controller but failed to
                  decode into a usable command. The RF layer worked;
                  the controller-side processing rejected the frame.
                  Common causes:
                    - S0/S2 security failure (MIC mismatch, stale key,
                      often after a re-inclusion).
                    - Malformed frame (bad CRC, truncated).
                    - Unknown / unsupported command class.
                    - Duplicate suppression.
                    - Unexpected protocol sequence.
                  -> Fix with: re-interview, re-inclusion (refreshes
                    security keys), firmware update.

  tx-drop         Frames the controller sent that never got a MAC-layer
                  ACK back after retries. Signals a reachability
                  problem: node out of range, obstacles, dead battery,
                  unreachable repeater hop.
                  -> Fix with: repeater placement, node relocation,
                    battery check.

  rx-drop-rate,   drops / (drops + success) per direction. High
  tx-drop-rate    tx-drop-rate -> mesh reachability problem; high
                  rx-drop-rate -> controller-side processing problem
                  (often security or interview). They rarely need the
                  same fix.

Data sources
------------
  Home Assistant's WebSocket + REST APIs provide entity / device / area
  registries and current + historical entity state. zwave-js-ui's
  socket.io (getNodes) provides the Z-Wave protocol (Mesh/LR) and the
  currently-configured priority / SUC return routes, which HA doesn't
  expose as entities.

Recorder retention
------------------
  Historical stats are queried from HA's recorder. The script reads
  recorder.purge_keep_days from /config/configuration.yaml and errors if
  --days exceeds it. HA's built-in default is 10 days.

Environment
-----------
  On first run, the script creates a venv at
  /root/.zwavectl_venv/ with its dependencies, then re-execs inside
  it.
"""

VENV_DIR = pathlib.Path("/root/.zwavectl_venv")
# Stamp file holding the VENV_DEPS that were last installed. A missing
# stamp means a half-built venv (pip failed mid-run); a stamp whose
# contents differ from the current VENV_DEPS means the dep set changed
# since the last install (e.g. a new dep added on an upgrade). Either
# case re-runs ``pip install`` (a no-op when packages are already
# present), so a venv from an older zwavectl never silently misses a
# newly-added dependency.
VENV_STAMP = VENV_DIR / ".installed"
API_KEY_FILE = pathlib.Path("/root/api-key")
# The policy file the param-manager view plans against. Defaults to the same
# file the blueprint targets (its ``config_file_path`` input defaults to
# ``zwave_parameter_manager.yaml``, which HA resolves under ``/config``).
PM_CONFIG_DEFAULT = pathlib.Path("/config/zwave_parameter_manager.yaml")
HA_URL = "http://homeassistant:8123"
ZWAVE_URL = "http://core-zwave-js:8091"
# The zwave-js *server* (not the 8091 zwave-js-ui socket): its
# start_listening dump carries the per-node value metadata the param
# resolver needs, which the 8091 getNodes() omits. Used by the
# param-manager view only.
ZWAVE_SERVER_URL = "ws://core-zwave-js:3000"
# Cap every blocking recv on the 3000 socket so a half-open server (connected
# but never framing) fails with a clear error instead of hanging the CLI.
ZWAVE_SERVER_RECV_TIMEOUT = 40
VENV_DEPS = [
    "python-socketio[asyncio_client]==5.11.3",
    "aiohttp",
    # param-manager view: the raw 3000 socket + the Node model the shared
    # adapter consumes.
    "websockets",
    # Pinned to the same version the shared source / adapter modules declare
    # and are tested against. This venv is isolated from HA's, so HA bundling
    # a different version is irrelevant: the wire read negotiates the schema
    # down to what this client parses (capped at MAX_SERVER_SCHEMA_VERSION),
    # and the integration code runs here against the client it was tested with.
    "zwave-js-server-python==0.73.0",
    # param-manager config: the shared pipeline loads the policy file with
    # PyYAML, so the host venv must carry it.
    "pyyaml",
]

# Columns that carry a list of days+1 values (latest first).
HISTORICAL_COLUMNS = [
    "ss",
    "ss-quality",
    "rtt",
    "rx",
    "tx",
    "rx-drop",
    "tx-drop",
    "rx-drop-rate",
    "tx-drop-rate",
]

# Columns derived in-Python from two entity-backed columns
# (``(success_col, drops_col)``). The rate is computed after
# the entity-fetch loop has populated the source columns.
_RATE_COLUMNS: dict[str, tuple[str, str]] = {
    "rx-drop-rate": ("rx", "rx-drop"),
    "tx-drop-rate": ("tx", "tx-drop"),
}

# Signal-strength classification thresholds (dBm), keyed by
# protocol. LR tolerates roughly 15 dB weaker signals than
# Classic Mesh because of its +14 dBm TX ceiling (vs 0 dBm)
# plus DSSS + Forward Error Correction. Each entry is
# ``(good_above, fair_above)``: anything above ``good_above``
# is "good", between the two is "fair", at or below
# ``fair_above`` is "poor".
_SS_THRESHOLDS: dict[str, tuple[int, int]] = {
    "Mesh": (-70, -85),
    "LR": (-80, -100),
}

# Single canonical ordered list of every column the tool
# understands. ``--cols all`` returns this verbatim.
#
# ``priority-route`` is the configured controller->node priority
# route (``node.applicationRoute``). ``suc-route`` is the SUC
# return route used for node->controller transmissions
# (``node.prioritySUCReturnRoute``). Splitting them lets users
# spot direction asymmetries (e.g. outbound applied, return
# still pending).
ALL_COLUMNS = [
    "node",
    "device",
    "location",
    "protocol",
    "ss",
    "ss-quality",
    "priority-route",
    "suc-route",
    "status",
    "last-seen",
    "battery",
    "power",
    "rx",
    "tx",
    "rx-drop",
    "tx-drop",
    "rx-drop-rate",
    "tx-drop-rate",
    "timeouts",
    "rtt",
    "route-speed",
    "max-speed",
    "neighbors",
    "manufacturer",
    "product",
    "product-code",
    "role",
    "security",
    "beaming",
    "firmware-dev",
    "firmware-sdk",
    "update",
    "plus",
    "interview",
]

# --cols aliases. ``defaults`` is the set of columns shown when
# --cols isn't specified. Other aliases are convenience
# groupings. Aliases are accepted in --cols only (not --sort),
# so sort always targets a single real column. Iteration order
# here drives the help-epilog Aliases block.
_COLUMN_ALIASES: dict[str, list[str]] = {
    "defaults": [
        "node",
        "device",
        "location",
        "protocol",
        "ss-quality",
    ],
    "routes": ["priority-route", "suc-route"],
    "firmware": ["firmware-dev", "firmware-sdk"],
    "stats": list(HISTORICAL_COLUMNS),
    "drops": ["rx-drop", "tx-drop"],
    "drop-rates": ["rx-drop-rate", "tx-drop-rate"],
}
# ``default`` is a long-standing singular synonym for
# ``defaults``. Kept working but hidden from help output.
_COLUMN_ALIASES["default"] = _COLUMN_ALIASES["defaults"]


def _build_aliases_block() -> str:
    """Render the Aliases help block from ``_COLUMN_ALIASES``.

    One line per alias, formatted as
    ``  <name>  <comma-separated expansion>``. ``all`` is
    handled separately in the template (it has a descriptive
    label rather than a column list), and the ``default``
    singular synonym is hidden.
    """
    lines: list[str] = []
    for alias, expansion in _COLUMN_ALIASES.items():
        if alias == "default":
            continue
        lines.append(f"  {alias:<14}  {', '.join(expansion)}")
    return "\n".join(lines)


_HELP_EPILOG = _HELP_EPILOG_TEMPLATE.format(
    aliases_block=_build_aliases_block(),
)

# Maps our short column key to the HA per-node stat entity suffix
# (the trailing portion of ``sensor.<device>_<suffix>`` that the
# zwave_js integration uses for diagnostic sensors).
#
# Entries must be mutually non-suffix-matching (no entry may end
# with another entry's value), because ``build_node_to_ha``
# matches via ``eid.endswith(f"_{suffix}")``. Two columns can
# share a suffix (see ``ss`` / ``ss-quality`` below); that's
# fine.
ENTITY_SUFFIX = {
    "ss": "signal_strength",
    # ss-quality backs onto the same HA sensor as ss; the raw
    # dBm value is reinterpreted as "good"/"fair"/"poor" during
    # row assembly.
    "ss-quality": "signal_strength",
    "rtt": "round_trip_time",
    "rx": "successful_commands_rx",
    "tx": "successful_commands_tx",
    "rx-drop": "commands_dropped_rx",
    "tx-drop": "commands_dropped_tx",
    "timeouts": "timed_out_responses",
    "status": "node_status",
    "last-seen": "last_seen",
    "battery": "battery_level",
}


# --- Bootstrap --------------------------------------------------


def bootstrap_venv() -> None:
    """Ensure a venv with the current VENV_DEPS exists at VENV_DIR.

    Creates the venv if missing, then runs ``pip install`` and records the
    installed VENV_DEPS in VENV_STAMP. The stamp gates the reinstall: it is
    absent on a half-built venv (pip failed mid-run) and stale whenever
    VENV_DEPS changed since the last install, so either case re-runs ``pip
    install`` (a no-op when the packages are already present).
    """
    vpy = VENV_DIR / "bin" / "python"
    want = "\n".join(VENV_DEPS)
    if vpy.exists() and VENV_STAMP.exists() and VENV_STAMP.read_text() == want:
        return
    if not vpy.exists():
        print(f"Creating venv at {VENV_DIR} (first run) ...", file=sys.stderr)
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
            check=True,
        )
    else:
        print(
            f"Installing/updating deps in {VENV_DIR} ...",
            file=sys.stderr,
        )
    subprocess.run(
        [str(VENV_DIR / "bin" / "pip"), "install", "--quiet", *VENV_DEPS],
        check=True,
    )
    VENV_STAMP.write_text(want)


def reexec_in_venv() -> None:
    vpy = str(VENV_DIR / "bin" / "python")
    if sys.executable == vpy:
        return
    os.execv(vpy, [vpy, os.path.abspath(__file__), *sys.argv[1:]])


# --- Fetchers ---------------------------------------------------


class ZwaveApiError(RuntimeError):
    """zwave-js-ui returned a ``success: false`` envelope.

    Distinct from ``socketio.exceptions.TimeoutError`` (the
    call never returned at all) and from ``TypeError`` (malformed
    response shape). Raised when the addon answers
    quickly but the driver reports a failure -- most commonly
    the ``"Z-Wave client not connected"`` state seen when the
    controller is wedged and zwave-js can't complete driver
    init. The top-level handler catches this so the user sees
    a clean message with controller-recovery guidance.
    """


# Max concurrent per-node route refresh nodes. zwave-js-ui
# serializes most controller calls anyway; dozens of parallel
# requests have been observed to stall the controller's serial
# interface. ``2`` keeps the connection pipelined so one slow
# node doesn't block progress on the rest, without queuing a
# thundering herd. Mirrored by the ZRM bridge's semaphore in
# ``custom_components/blueprint_toolkit/zwave_route_manager/bridge.py``.
_ROUTE_REFRESH_CONCURRENCY = 2


# --- API payload shapes -----------------------------------------
#
# TypedDicts over the read-only JSON blobs this tool inspects: HA
# registry rows, the zwave-js node model, HA state / history
# entries, and the zwave-js-ui / HA / zwave-js-server reply
# envelopes. They declare only the keys this tool reads
# (``total=False`` -- the real payloads carry many more), so a typo
# in a key name is a type error instead of a silent miss. Raw blobs
# we never inspect (e.g. the start_listening node state handed
# straight to ``zwave_js_server``'s ``Node``) stay untyped.


class DeviceRow(TypedDict, total=False):
    """An HA device-registry row."""

    id: str
    identifiers: list[list[str]]
    area_id: str | None
    name: str | None
    name_by_user: str | None


class EntityRow(TypedDict, total=False):
    """An HA entity-registry row."""

    platform: str
    device_id: str | None
    entity_id: str
    device_class: str | None
    original_device_class: str | None


class AreaRow(TypedDict, total=False):
    """An HA area-registry row."""

    area_id: str
    name: str | None


class HaStateAttributes(TypedDict, total=False):
    """The subset of an HA state's ``attributes`` this tool reads."""

    device_class: str | None


class HaState(TypedDict, total=False):
    """An HA state object (``/api/states``) or minimal history entry
    (``/api/history``)."""

    entity_id: str
    state: str
    last_changed: str
    last_updated: str
    attributes: HaStateAttributes


class Route(TypedDict, total=False):
    """A zwave-js priority / SUC-return route."""

    repeaters: list[int]


class Lwr(TypedDict, total=False):
    """A node's last-working-route statistics."""

    protocolDataRate: int


class NodeStatistics(TypedDict, total=False):
    """The subset of a node's ``statistics`` block this tool reads."""

    lwr: Lwr


class FirmwareUpdate(TypedDict, total=False):
    """An ``availableFirmwareUpdates`` entry."""

    version: str


class ZwaveNode(TypedDict, total=False):
    """The subset of a zwave-js node model this tool reads."""

    id: int
    name: str
    protocol: int
    isListening: bool
    statistics: NodeStatistics
    applicationRoute: Route | None
    prioritySUCReturnRoute: Route | None
    zwavePlusVersion: int
    zwavePlusRoleType: int
    manufacturer: str
    productDescription: str
    productLabel: str
    security: str
    supportsBeaming: bool
    firmwareVersion: str
    sdkVersion: str
    interviewStage: str
    maxDataRate: int
    availableFirmwareUpdates: list[FirmwareUpdate]


class ZwaveApiResponse(TypedDict, total=False):
    """A zwave-js-ui socketio ``ZWAVE_API`` reply envelope."""

    success: bool
    message: str
    result: Any


class HaWsResponse(TypedDict, total=False):
    """An HA websocket reply envelope."""

    type: str
    result: Any


class ServerState(TypedDict, total=False):
    """The ``state`` block of a zwave-js-server ``start_listening``."""

    nodes: list[dict[str, Any]]


class ServerResult(TypedDict, total=False):
    """The ``result`` block of a zwave-js-server message."""

    state: ServerState


class ServerMessage(TypedDict, total=False):
    """A zwave-js-server (port 3000) message frame."""

    messageId: str
    maxSchemaVersion: int
    result: ServerResult


def _api_response(raw: Any) -> ZwaveApiResponse:
    """Coerce a raw zwave-js-ui socketio reply to the envelope shape; a
    non-dict reply becomes an empty (all-keys-absent) envelope."""
    return cast("ZwaveApiResponse", raw) if isinstance(raw, dict) else {}


async def fetch_zwave_nodes(
    use_snapshot_data: bool = False,
) -> dict[int, ZwaveNode]:
    """Bulk node fetch with route fields refreshed per-node.

    The bulk ``getNodes`` snapshot's ``applicationRoute`` and
    ``prioritySUCReturnRoute`` fields can flap to ``None``
    while the controller still holds the route -- observed in
    practice, plausibly a cache-invalidation race in
    zwave-js-ui. The web UI sidesteps this by hitting per-node
    ``getPriorityRoute`` / ``getPrioritySUCReturnRoute`` for
    its routing display, so we do the same here.

    Refreshes run concurrently (see
    ``_ROUTE_REFRESH_CONCURRENCY``) on a single socket.io
    connection. The controller (node 1) has no inbound route
    to itself and is skipped entirely. Z-Wave LR nodes (ID
    256+) are also skipped: LR is a direct-star topology with
    no mesh, so priority routes and priority SUC return
    routes don't apply, and on some controller firmware
    versions ``getPriorityRoute`` for an LR node wedges the
    controller.

    When ``use_snapshot_data`` is True, the per-node refresh
    is skipped entirely and the bulk snapshot's route fields
    are returned as-is. Those values may be stale (the
    snapshot is updated only when routes are assigned or at
    driver startup). Use only when the controller can't
    service the live queries and some data is better than
    none.
    """
    # Keep this local: the dependency is installed only in the
    # bootstrapped script venv after re-exec.
    import socketio

    sio = socketio.AsyncClient()
    await sio.connect(ZWAVE_URL, socketio_path="/socket.io")
    try:
        resp = _api_response(
            await sio.call(
                "ZWAVE_API",
                {"api": "getNodes", "args": []},
                timeout=10.0,
            )
        )
        # zwave-js-ui envelope: ``success`` False with a
        # ``message`` means the addon is up but the driver
        # can't service the call (e.g. ``"Z-Wave client not
        # connected"`` when the controller's wedged and
        # driver init is looping on timeouts). Route to a
        # dedicated exception so the top-level handler can
        # print a clean message with controller-recovery
        # guidance instead of a traceback.
        if resp.get("success") is False:
            message = str(resp.get("message") or "no message")
            raise ZwaveApiError(f"getNodes failed: {message}")
        result = resp.get("result")
        if not isinstance(result, list):
            raise TypeError(
                f"getNodes returned unexpected shape: {resp!r}",
            )
        nodes: dict[int, ZwaveNode] = {
            n["id"]: cast("ZwaveNode", n)
            for n in result
            if isinstance(n, dict) and "id" in n
        }
        if use_snapshot_data:
            return nodes
        sem = asyncio.Semaphore(_ROUTE_REFRESH_CONCURRENCY)

        async def _refresh(nid: int) -> None:
            async with sem:
                ar_raw, psr_raw = await asyncio.gather(
                    sio.call(
                        "ZWAVE_API",
                        {"api": "getPriorityRoute", "args": [nid]},
                        timeout=5.0,
                    ),
                    sio.call(
                        "ZWAVE_API",
                        {
                            "api": "getPrioritySUCReturnRoute",
                            "args": [nid],
                        },
                        timeout=5.0,
                    ),
                )
            ar_resp = _api_response(ar_raw)
            psr_resp = _api_response(psr_raw)
            ar = ar_resp.get("result") if ar_resp.get("success") else None
            psr = psr_resp.get("result") if psr_resp.get("success") else None
            nodes[nid]["applicationRoute"] = ar
            nodes[nid]["prioritySUCReturnRoute"] = psr

        # Skip the controller (no inbound route to itself, so
        # the refresh would be wasted RPCs) and LR nodes (IDs
        # 256+: direct star topology, no priority routes, and
        # ``getPriorityRoute`` on LR has been observed to wedge
        # the controller on some firmware).
        await asyncio.gather(
            *(_refresh(nid) for nid in nodes if nid != 1 and nid < 256),
        )
    finally:
        await sio.disconnect()
    return nodes


async def fetch_zwave_neighbors(
    node_ids: list[int],
) -> dict[int, list[int]]:
    """Fetch neighbor lists for the given nodes.

    Opens a single socket.io connection and calls
    ``getNodeNeighbors`` serially per node. zwave-js-ui may
    serialize these on the controller anyway, and batching
    avoids opening one connection per node. Runs only when the
    user asks for the ``neighbors`` column (~50ms per call on
    a typical install).
    """
    # Keep this local: the dependency is installed only in the
    # bootstrapped script venv after re-exec.
    import socketio

    out: dict[int, list[int]] = {}
    if not node_ids:
        return out
    sio = socketio.AsyncClient()
    await sio.connect(ZWAVE_URL, socketio_path="/socket.io")
    try:
        for nid in node_ids:
            r = _api_response(
                await sio.call(
                    "ZWAVE_API",
                    {"api": "getNodeNeighbors", "args": [nid]},
                    timeout=5.0,
                )
            )
            if r.get("success"):
                result = r.get("result")
                if isinstance(result, list):
                    out[nid] = [x for x in result if isinstance(x, int)]
    finally:
        await sio.disconnect()
    return out


async def fetch_ha_registries(
    api_key: str,
) -> tuple[list[EntityRow], dict[str, DeviceRow], dict[str, AreaRow]]:
    """Return (entities, devices_by_id, areas_by_id)."""
    # Keep this local: the dependency is installed only in the
    # bootstrapped script venv after re-exec.
    import aiohttp

    async with (
        aiohttp.ClientSession() as session,
        session.ws_connect(f"{HA_URL}/api/websocket") as ws,
    ):
        await ws.receive_json()  # auth_required
        await ws.send_json({"type": "auth", "access_token": api_key})
        auth_resp = cast("HaWsResponse", await ws.receive_json())
        if auth_resp.get("type") != "auth_ok":
            raise RuntimeError(
                f"HA WebSocket auth failed: {auth_resp!r}",
            )

        next_id = 0

        # Serial send/receive is safe here because we never
        # subscribe to events, so no asynchronous messages
        # (state_changed, etc.) can land between our request
        # and its response. If a future change adds an
        # event subscription, this will need to correlate
        # responses by ``id`` instead.
        async def call(command: str) -> Any:
            nonlocal next_id
            next_id += 1
            await ws.send_json({"id": next_id, "type": command})
            resp = cast("HaWsResponse", await ws.receive_json())
            return resp.get("result") or []

        entities = cast(
            "list[EntityRow]", await call("config/entity_registry/list")
        )
        devices = cast(
            "list[DeviceRow]", await call("config/device_registry/list")
        )
        areas = cast("list[AreaRow]", await call("config/area_registry/list"))

    return (
        entities,
        {d["id"]: d for d in devices},
        {a["area_id"]: a for a in areas},
    )


async def fetch_ha_states(api_key: str) -> dict[str, str]:
    """Return entity_id -> current state (as string) for all HA entities."""
    # Keep this local: the dependency is installed only in the
    # bootstrapped script venv after re-exec.
    import aiohttp

    headers = {"Authorization": f"Bearer {api_key}"}
    async with (
        aiohttp.ClientSession() as session,
        session.get(f"{HA_URL}/api/states", headers=headers) as r,
    ):
        r.raise_for_status()
        states = cast("list[HaState]", await r.json())
    return {s["entity_id"]: s["state"] for s in states}


async def _fetch_entity_history(
    api_key: str,
    entity_ids: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[HaState]]:
    """Raw HA history for a set of entities over ``[start, end]``.

    Returns ``{entity_id: [HaState, ...]}`` for each entity with any history
    in the window (entities with none are absent). One batched
    ``/api/history/period`` request per 30 entities keeps the
    ``filter_entity_id`` URL parameter within HA's request-size limits.

    The shared history transport. Callers apply their own extraction to the
    per-entity state lists this returns -- e.g. the state active at a target
    time, or the last transition to a given state.
    """
    # Keep this local: the dependency is installed only in the
    # bootstrapped script venv after re-exec.
    import aiohttp

    if not entity_ids:
        return {}

    headers = {"Authorization": f"Bearer {api_key}"}
    batch_size = 30
    out: dict[str, list[HaState]] = {}

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(entity_ids), batch_size):
            chunk = entity_ids[i : i + batch_size]
            url = f"{HA_URL}/api/history/period/{start.isoformat()}"
            params = {
                "filter_entity_id": ",".join(chunk),
                "end_time": end.isoformat(),
                "minimal_response": "true",
                "no_attributes": "true",
            }
            async with session.get(
                url,
                headers=headers,
                params=params,
            ) as r:
                r.raise_for_status()
                data = await r.json()
            if not isinstance(data, list):
                continue
            for ent_hist_raw in data:
                if not isinstance(ent_hist_raw, list) or not ent_hist_raw:
                    continue
                ent_hist = cast("list[HaState]", ent_hist_raw)
                eid = ent_hist[0].get("entity_id")
                if eid is not None:
                    out[eid] = ent_hist
    return out


async def fetch_ha_history(
    api_key: str,
    entity_ids: list[str],
    day_offsets: list[int],
) -> dict[str, dict[int, str]]:
    """Fetch state at each day_offset for each entity.

    Returns ``{entity_id: {day_offset: state_string}}``. Missing
    readings are simply absent from the inner dict.

    Strategy: query the full window (oldest target -> now) once via
    ``_fetch_entity_history``, then for each target day pick the last state
    with ``last_changed <= target`` -- i.e., the state that was active at
    that time. This handles sleepy nodes that only transmit once per N days:
    if there's any reading in the full window older than the target, it's
    used.
    """
    if not entity_ids or not day_offsets:
        return {eid: {} for eid in entity_ids}

    now = datetime.now(UTC)
    max_day = max(day_offsets)
    # 12h slack lets us find a state that was active at the
    # oldest target even if the most recent change was slightly
    # before our window starts.
    fetch_start = now - timedelta(days=max_day + 1, hours=12)
    targets = {day: now - timedelta(days=day) for day in day_offsets}
    out: dict[str, dict[int, str]] = {eid: {} for eid in entity_ids}

    history = await _fetch_entity_history(api_key, entity_ids, fetch_start, now)
    for eid, ent_hist in history.items():
        if eid not in out:
            continue
        for day, target in targets.items():
            state = _state_at_or_before(ent_hist, target)
            if state is not None:
                out[eid][day] = state
    return out


def _read_recorder_keep_days() -> int:
    """Parse ``purge_keep_days`` from HA's configuration.yaml.

    Handles both inline ``recorder:`` blocks and the
    ``recorder: !include <file>`` pattern. Falls back to HA's
    built-in default (10) when the setting can't be determined
    -- errs on the side of *more* restrictive retention so we
    don't silently accept a user ``--days`` that would return
    empty history.

    The ``!include_dir_*`` family
    (``!include_dir_list``, ``!include_dir_named``,
    ``!include_dir_merge_list``, ``!include_dir_merge_named``)
    is not recognized -- those configs fall through to the
    default, which is the safer direction (under-estimates
    retention rather than over-estimates).
    """
    if not HA_CONFIG_YAML.exists():
        return DEFAULT_RECORDER_KEEP_DAYS
    text = HA_CONFIG_YAML.read_text()
    # Two shapes to handle:
    #   recorder: !include foo.yaml
    #   recorder:\n  purge_keep_days: N\n  ...
    m = re.search(
        r"^recorder:[ \t]*(?:(!include[ \t]+\S+)|\n((?:[ \t]+.*\n?)+))",
        text,
        re.MULTILINE,
    )
    if not m:
        return DEFAULT_RECORDER_KEEP_DAYS
    include_directive = m.group(1) or ""
    inline_body = m.group(2) or ""
    if include_directive:
        include_target = include_directive.split(maxsplit=1)[-1].strip()
        include_path = HA_CONFIG_YAML.parent / include_target
        if include_path.exists():
            inline_body = include_path.read_text()
    km = re.search(r"^\s*purge_keep_days:\s*(\d+)", inline_body, re.MULTILINE)
    if km:
        return int(km.group(1))
    return DEFAULT_RECORDER_KEEP_DAYS


def _state_at_or_before(
    history: list[HaState],
    target: datetime,
) -> str | None:
    """Return the state that was active at ``target``.

    Walks the chronologically-sorted history and returns the
    last state whose ``last_changed`` is <= target. Returns
    ``None`` if no valid state-value is found at or before
    target.
    """
    best: str | None = None
    for s in history:
        lc_str = s.get("last_changed") or s.get("last_updated")
        if not lc_str:
            continue
        try:
            lc = datetime.fromisoformat(lc_str)
        except ValueError:
            continue
        if lc > target:
            break
        state = s.get("state")
        if state in (None, "unavailable", "unknown", ""):
            continue
        best = state
    return best


# --- Registry plumbing ------------------------------------------


def node_ids_by_device(
    devices_by_id: dict[str, DeviceRow],
) -> dict[str, int]:
    """Map HA ``device_id`` -> zwave ``node_id`` by reverse-parsing each
    device's ``("zwave_js", "<home_id>-<node_id>")`` identifier.

    The standalone CLI has no driver to call ``get_device_id`` against, so it
    parses the identifier string. The extended identifier form appends more
    ``-``-joined fields, but ``node_id`` stays at index 1. identifiers order
    is non-deterministic, so the first ``zwave_js`` identifier that parses
    wins.
    """
    dev_to_node: dict[str, int] = {}
    for dev in devices_by_id.values():
        for ident in dev.get("identifiers") or []:
            if (
                not isinstance(ident, (list, tuple))
                or len(ident) < 2
                or ident[0] != "zwave_js"
            ):
                continue
            parts = str(ident[1]).split("-")
            if len(parts) >= 2 and parts[1].isdigit():
                dev_to_node[dev["id"]] = int(parts[1])
                break
    return dev_to_node


@dataclass(frozen=True)
class NodeHaInfo:
    """HA-derived per-node context for the list view: display name, area, and
    the ``{col_key: entity_id}`` map of per-node diagnostic stat sensors
    (signal_strength, round_trip_time, etc). An absent stat entry means the
    entity doesn't exist for that node -- rendered as ``--``."""

    device_name: str
    area_name: str
    stat_entities: dict[str, str]


def build_node_to_ha(
    devices_by_id: dict[str, DeviceRow],
    areas_by_id: dict[str, AreaRow],
    entities: list[EntityRow],
) -> dict[int, NodeHaInfo]:
    """Map each zwave node_id to its ``NodeHaInfo``."""
    dev_to_node = node_ids_by_device(devices_by_id)

    out: dict[int, NodeHaInfo] = {}
    for dev_id, node_id in dev_to_node.items():
        dev = devices_by_id[dev_id]
        area_id = dev.get("area_id")
        area_name = ""
        if area_id and area_id in areas_by_id:
            area_name = areas_by_id[area_id].get("name") or ""
        out[node_id] = NodeHaInfo(
            device_name=dev.get("name_by_user") or dev.get("name") or "",
            area_name=area_name,
            stat_entities={},
        )

    # Attach per-node stat entity_ids by matching on device_id and
    # entity_id suffix.
    for ent in entities:
        if ent.get("platform") != "zwave_js":
            continue
        dev_id = ent.get("device_id") or ""
        if dev_id not in dev_to_node:
            continue
        node_id = dev_to_node[dev_id]
        eid = ent.get("entity_id") or ""
        for col, suffix in ENTITY_SUFFIX.items():
            # No break: multiple columns may share a suffix
            # (e.g. ss and ss-quality both back onto the
            # signal_strength sensor). Suffixes don't overlap
            # otherwise so this is still at most one match per
            # column per entity.
            if eid.endswith(f"_{suffix}"):
                out[node_id].stat_entities[col] = eid
    return out


# --- Row assembly -----------------------------------------------


# Historical cell values are scalar when --days == 0, otherwise
# a list of length days+1 ([latest, -1d, -2d, ...]). Most
# columns hold numbers; ``ss-quality`` holds the bucket string.
HistoricalValue = int | float | str | None
HistoricalCell = HistoricalValue | list[HistoricalValue]


@dataclass
class Row:
    """Per-node display row.

    Field names mirror the public column keys with dashes
    converted to underscores (``rx-drop`` -> ``rx_drop``).
    Historical columns hold either a scalar or a
    ``[latest, -1d, -2d, ...]`` list (see ``HISTORICAL_COLUMNS``
    and ``--days``).
    """

    node: int
    device: str
    location: str
    protocol: str
    priority_route: str
    suc_route: str
    power: str
    manufacturer: str
    product: str
    product_code: str
    security: str
    beaming: str
    firmware_dev: str | None
    firmware_sdk: str | None
    plus: str
    interview: str
    route_speed: int | None
    max_speed: int | None
    role: int | None
    update: str
    neighbors: list[int] | None
    ss: HistoricalCell
    ss_quality: HistoricalCell
    rtt: HistoricalCell
    rx: HistoricalCell
    tx: HistoricalCell
    rx_drop: HistoricalCell
    tx_drop: HistoricalCell
    rx_drop_rate: HistoricalCell
    tx_drop_rate: HistoricalCell
    timeouts: int | float | None
    battery: int | float | None
    status: str | None
    last_seen: str | None


def _row_attr(col: str) -> str:
    """Public column key -> ``Row`` attribute name.

    Column keys use dashes for readability; ``Row`` fields use
    underscores because dashes aren't valid Python identifiers.
    """
    return col.replace("-", "_")


# Sanity check: every ALL_COLUMNS entry must map to a Row field
# and every Row field must correspond to an ALL_COLUMNS entry.
# Caught at import time -- a forgotten column shouldn't get as
# far as the render path.
_ROW_FIELDS = {f.name for f in fields(Row)}
_EXPECTED_ROW_FIELDS = {_row_attr(c) for c in ALL_COLUMNS}
if _ROW_FIELDS != _EXPECTED_ROW_FIELDS:
    missing = _EXPECTED_ROW_FIELDS - _ROW_FIELDS
    extra = _ROW_FIELDS - _EXPECTED_ROW_FIELDS
    raise RuntimeError(
        f"Row / ALL_COLUMNS mismatch: missing={sorted(missing)} "
        f"extra={sorted(extra)}",
    )


def _parse_numeric(state: str | None) -> int | float | None:
    if state is None or state in ("unavailable", "unknown", ""):
        return None
    try:
        f = float(state)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def _route_label(
    route: Route | None,
    node_to_ha: dict[int, NodeHaInfo],
) -> str:
    """Human label for a zwave-js ``applicationRoute`` or
    ``prioritySUCReturnRoute`` dict.

    A repeater-based priority route renders as the repeater's
    device name (with ``(+N)`` for N extra hops). Anything
    else renders as ``DASH``.
    """
    if not isinstance(route, dict):
        return DASH
    reps = route.get("repeaters")
    if not isinstance(reps, list) or not reps:
        return DASH
    rid = reps[0]
    info = node_to_ha.get(rid)
    label = (info.device_name if info else "") or f"node {rid}"
    if len(reps) > 1:
        label += f" (+{len(reps) - 1})"
    return label


def build_rows(
    zwave_nodes: dict[int, ZwaveNode],
    node_to_ha: dict[int, NodeHaInfo],
    current_states: dict[str, str],
    history: dict[str, dict[int, str]],
    day_offsets: list[int],
    neighbors: dict[int, list[int]] | None = None,
) -> list[Row]:
    """Assemble display rows.

    Historical columns become lists of ``len(day_offsets) + 1``
    numbers (or ``None``) in order: [latest, -day_offsets[0],
    -day_offsets[1], ...]. When ``day_offsets`` is empty the
    historical columns collapse to a single scalar (the latest).
    """
    rows: list[Row] = []
    for nid, n in zwave_nodes.items():
        if nid == 1:
            continue
        stats = n.get("statistics") or {}
        ha = node_to_ha.get(nid)
        stat_ents: dict[str, str] = ha.stat_entities if ha else {}
        plus_ver = n.get("zwavePlusVersion")
        # Internal working dict keyed by public column name
        # (dashes). Converted to underscore keys when the Row
        # dataclass is constructed at the bottom of the loop.
        cells: dict[str, Any] = {
            "node": nid,
            "device": (ha.device_name if ha else "")
            or n.get("name")
            or f"node {nid}",
            "location": ha.area_name if ha else "",
            "protocol": "LR" if n.get("protocol") == 1 else "Mesh",
            "priority-route": _route_label(
                n.get("applicationRoute"),
                node_to_ha,
            ),
            "suc-route": _route_label(
                n.get("prioritySUCReturnRoute"),
                node_to_ha,
            ),
            # Power source is derived: always-listening (line-
            # powered) devices report isListening=True; FLiRS
            # and sleepy nodes are battery-backed regardless of
            # their wake pattern.
            "power": "Mains" if n.get("isListening") else "Battery",
            "manufacturer": n.get("manufacturer") or "",
            "product": n.get("productDescription") or "",
            "product-code": n.get("productLabel") or "",
            "security": n.get("security") or "",
            "beaming": "yes" if n.get("supportsBeaming") else "no",
            "firmware-dev": n.get("firmwareVersion") or None,
            "firmware-sdk": n.get("sdkVersion") or None,
            "plus": f"v{plus_ver}" if plus_ver is not None else "no",
            "interview": n.get("interviewStage") or "",
            # ``lwr.protocolDataRate`` is the actual rate of the
            # last working route; ``maxDataRate`` is the node's
            # advertised cap. Pair them to spot negotiation drops.
            "route-speed": ((stats.get("lwr") or {}).get("protocolDataRate")),
            "max-speed": n.get("maxDataRate"),
            "role": n.get("zwavePlusRoleType"),
            "update": _fmt_update(n.get("availableFirmwareUpdates")),
            "neighbors": (neighbors or {}).get(nid),
        }
        # Historical columns -> list (or scalar when days=0).
        # ``ss-quality`` is derived from the SS value + protocol:
        # raw dBm gets bucketed to "good"/"fair"/"poor" with the
        # protocol-specific thresholds. ``_RATE_COLUMNS`` are
        # derived in a post-pass from their source counter cols.
        protocol = cells["protocol"]
        for col in HISTORICAL_COLUMNS:
            if col in _RATE_COLUMNS:
                continue  # computed below once sources are in
            eid = stat_ents.get(col)
            raws: list[str | None] = [
                current_states.get(eid) if eid else None,
            ]
            for d in day_offsets:
                raws.append(history.get(eid, {}).get(d) if eid else None)
            values: list[HistoricalValue]
            if col == "ss-quality":
                values = [
                    _ss_quality(_parse_numeric(r), protocol) for r in raws
                ]
            else:
                values = [_parse_numeric(r) for r in raws]
            cells[col] = values if day_offsets else values[0]
        # Derived rate columns: drops / (drops + success) at each
        # time point. Source cols are already populated above.
        for rate_col, (success_col, drops_col) in _RATE_COLUMNS.items():
            s_val = cells.get(success_col)
            d_val = cells.get(drops_col)
            if (
                day_offsets
                and isinstance(s_val, list)
                and isinstance(d_val, list)
            ):
                cells[rate_col] = [
                    _drop_rate(s, d) for s, d in zip(s_val, d_val, strict=True)
                ]
            else:
                cells[rate_col] = _drop_rate(s_val, d_val)
        # Non-historical scalar stats. ``status`` and
        # ``last-seen`` are stored as raw state strings;
        # ``_cell`` does the user-facing formatting.
        for col in ("timeouts", "battery"):
            eid = stat_ents.get(col)
            cells[col] = _parse_numeric(
                current_states.get(eid) if eid else None,
            )
        for col in ("status", "last-seen"):
            eid = stat_ents.get(col)
            raw = current_states.get(eid) if eid else None
            if raw in (None, "unavailable", "unknown", ""):
                cells[col] = None
            else:
                cells[col] = raw
        rows.append(Row(**{_row_attr(k): v for k, v in cells.items()}))
    return rows


# --- Rendering --------------------------------------------------


ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_RED = "\033[31m"
ANSI_RESET = "\033[0m"
# Use a plain ASCII hyphen for the "no data" placeholder. The
# em-dash (U+2014) we used originally is Unicode-ambiguous-width
# -- rendered as 1 column in most terminals but 2 in some, which
# broke column alignment on rows mixing null and non-null cells.
DASH = "-"


def _ss_quality(v: float | None, protocol: str | None) -> str | None:
    """Bucket a raw SS value into ``good``/``fair``/``poor``.

    Thresholds vary by ``protocol`` (see ``_SS_THRESHOLDS``).
    Falls back to Mesh thresholds when protocol is unknown.
    Returns ``None`` for a null input.
    """
    if v is None:
        return None
    good_above, fair_above = _SS_THRESHOLDS.get(
        protocol or "Mesh",
        _SS_THRESHOLDS["Mesh"],
    )
    if v > good_above:
        return "good"
    if v > fair_above:
        return "fair"
    return "poor"


def _ss_color(v: float | None, protocol: str | None) -> str:
    """ANSI color for a numeric SS reading, protocol-aware."""
    label = _ss_quality(v, protocol)
    if label == "good":
        return ANSI_GREEN
    if label == "fair":
        return ANSI_YELLOW
    if label == "poor":
        return ANSI_RED
    return ""


_SS_QUALITY_COLORS = {
    "good": ANSI_GREEN,
    "fair": ANSI_YELLOW,
    "poor": ANSI_RED,
}


def _fmt_num(v: float | None) -> str:
    if v is None:
        return DASH
    if isinstance(v, float) and not v.is_integer():
        return f"{v:.1f}"
    return str(int(v))


def _fmt_ss(
    v: float | None,
    use_color: bool,
    protocol: str | None = None,
) -> str:
    s = _fmt_num(v)
    if not use_color or v is None:
        return s
    return f"{_ss_color(v, protocol)}{s}{ANSI_RESET}"


def _fmt_ss_quality(label: str | None, use_color: bool) -> str:
    if not label:
        return DASH
    if not use_color:
        return label
    color = _SS_QUALITY_COLORS.get(label, "")
    return f"{color}{label}{ANSI_RESET}" if color else label


def _fmt_history_sub(
    v: Any,
    col: str,
    use_color: bool,
    protocol: str | None,
) -> str:
    """Format one sub-value of a historical cell for ``col``."""
    if col == "ss":
        return _fmt_ss(v, use_color, protocol)
    if col == "ss-quality":
        return _fmt_ss_quality(v, use_color)
    if col in _RATE_COLUMNS:
        return _fmt_drop_rate(v, use_color)
    return _fmt_num(v)


def _fmt_history_cell(
    values: Any,
    col: str,
    use_color: bool,
    position_widths: list[int] | None = None,
    protocol: str | None = None,
) -> str:
    """Render a historical (list) cell.

    ``position_widths[i]`` is the max width of sub-value *i*
    across all rows for this column. Each sub-value is
    right-aligned to that width so the daily sub-columns line
    up vertically (e.g. ``-`` vs ``-65`` no longer shift the
    neighbouring values horizontally). Falls back to
    un-padded rendering when widths aren't supplied (scalar
    path or callers that haven't pre-computed widths).
    """
    if isinstance(values, list):
        parts: list[str] = []
        for i, v in enumerate(values):
            s = _fmt_history_sub(v, col, use_color, protocol)
            if position_widths is not None and i < len(position_widths):
                pad = max(0, position_widths[i] - _visible_len(s))
                s = " " * pad + s
            parts.append(s)
        return " ".join(parts)
    # Scalar path (days=0).
    return _fmt_history_sub(values, col, use_color, protocol)


def _fmt_last_seen(state: str | None) -> str:
    """Format an ISO timestamp as a compact relative age.

    Output tiers: ``<Ns>``, ``<Nm>``, ``<Nh>``, ``<Nd>``, ``<Nmo>``.
    Clock skew (timestamp in the future) is clamped to ``now``.
    """
    if not state:
        return DASH
    try:
        t = datetime.fromisoformat(state)
    except ValueError:
        return DASH
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - t
    secs = int(delta.total_seconds())
    if secs < 1:
        return "now"
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 60:
        return f"{days}d"
    return f"{days // 30}mo"


def _fmt_battery(v: float | None) -> str:
    if v is None:
        return DASH
    return str(int(v))


def _drop_rate(
    success: Any,
    drops: Any,
) -> float | None:
    """Drop fraction ``drops / (drops + success)`` in ``[0, 1]``.

    Returns ``None`` when both counters are missing or when the
    node has no activity (``total == 0``); either case means
    the rate is meaningless, not zero.
    """
    s = success if isinstance(success, (int, float)) else None
    d = drops if isinstance(drops, (int, float)) else None
    if s is None and d is None:
        return None
    # Explicit None-coalescing (not ``x or 0``) so a legitimate
    # zero counter stays zero -- ``bool(0) is False`` would
    # otherwise conflate "no data" and "measured zero".
    s_val: float = 0.0 if s is None else float(s)
    d_val: float = 0.0 if d is None else float(d)
    total = s_val + d_val
    if total == 0:
        return None
    return d_val / total


def _fmt_drop_rate(rate: float | None, use_color: bool) -> str:
    """Format a drop fraction as an integer percent (unit in header).

    Thresholds: green < 1%, yellow 1-5%, red > 5%. A non-zero
    rate that would round to 0 is shown as ``<1`` so a trickle
    of drops is visible.
    """
    if rate is None:
        return DASH
    pct = rate * 100
    if pct == 0:
        s = "0"
    elif pct < 1:
        s = "<1"
    else:
        s = str(round(pct))
    if not use_color:
        return s
    if pct < 1:
        color = ANSI_GREEN
    elif pct <= 5:
        color = ANSI_YELLOW
    else:
        color = ANSI_RED
    return f"{color}{s}{ANSI_RESET}"


def _fmt_update(updates: list[FirmwareUpdate] | None) -> str:
    """Format ``availableFirmwareUpdates`` into a cell string.

    ``None`` / empty list -> ``"no"``. Otherwise surface the
    first update's version: ``"yes (v<ver>)"``. zwave-js-ui
    orders by relevance so the first entry is usually the
    recommended update.
    """
    if not isinstance(updates, list) or not updates:
        return "no"
    ver = updates[0].get("version")
    if ver:
        return f"yes (v{ver})"
    return "yes"


def _fmt_role(v: int | None) -> str:
    if v is None:
        return DASH
    return ZWAVE_PLUS_ROLES.get(v, f"?{v}")


def _fmt_route_speed(v: int | None) -> str:
    if v is None:
        return DASH
    return _PROTOCOL_DATA_RATE.get(v, f"?{v}")


def _fmt_max_speed(v: int | None) -> str:
    if v is None:
        return DASH
    return _MAX_DATA_RATE.get(v, f"?{v}")


def _fmt_neighbors(v: list[int] | None) -> str:
    if v is None:
        return DASH
    if not v:
        return "none"
    return " ".join(str(n) for n in v)


def _fmt_version(v: str | None) -> str:
    """``"1.2.3"`` -> ``"v1.2.3"``; empty -> DASH."""
    if not v:
        return DASH
    return f"v{v}"


_COLUMN_HEADERS = {
    "node": "Node",
    "device": "Device",
    "location": "Location",
    "protocol": "Protocol",
    "ss": "SS (dBm)",
    "ss-quality": "SS Quality",
    "priority-route": "Priority Route",
    "suc-route": "SUC Route",
    "status": "Status",
    "last-seen": "Last Seen",
    "battery": "Battery (%)",
    "power": "Power",
    "rx": "RX",
    "tx": "TX",
    "rx-drop": "RX Drop",
    "tx-drop": "TX Drop",
    "rx-drop-rate": "RX Drop Rate (%)",
    "tx-drop-rate": "TX Drop Rate (%)",
    "timeouts": "Timeouts",
    "rtt": "RTT (ms)",
    "route-speed": "Route Speed",
    "max-speed": "Max Speed",
    "neighbors": "Neighbors",
    "manufacturer": "Manufacturer",
    "product": "Product",
    "product-code": "Product Code",
    "role": "Role",
    "security": "Security",
    "beaming": "Beaming",
    "firmware-dev": "Firmware DEV",
    "firmware-sdk": "Firmware SDK",
    "update": "Update",
    "plus": "Plus",
    "interview": "Interview",
}

# zwavePlusRoleType -> label. zwave-js enum names are long
# ("SleepingListeningSlave") so we abbreviate while keeping the
# role-kind clear.
ZWAVE_PLUS_ROLES = {
    0: "CentralCtrl",
    1: "SubCtrl",
    2: "PortableCtrl",
    3: "PortableRepCtrl",
    4: "PortableSlave",
    5: "AlwaysOn",
    6: "SleepingReporting",
    7: "SleepingListening",
}

# ``protocolDataRate`` (statistics.lwr) wire values.
_PROTOCOL_DATA_RATE: dict[int, str] = {
    1: "9.6k",
    2: "40k",
    3: "100k",
    4: "LR",
}

# ``maxDataRate`` is in raw bps.
_MAX_DATA_RATE: dict[int, str] = {
    9600: "9.6k",
    40000: "40k",
    100000: "100k",
}

# Cells right-aligned for number-heavy columns so scalar
# values line up visually. Historical (list) columns, route
# columns, and status stay left-aligned. All *headers* are
# left-aligned regardless of cell alignment.
_CELL_RIGHT_ALIGNED = {
    "node",
    "last-seen",
    "battery",
    "rx",
    "tx",
    "rx-drop",
    "tx-drop",
    "rx-drop-rate",
    "tx-drop-rate",
    "timeouts",
    "rtt",
    "route-speed",
    "max-speed",
}


def _visible_len(s: str) -> int:
    out = 0
    i = 0
    while i < len(s):
        if s[i] == "\033":
            j = s.find("m", i)
            if j == -1:
                return out + len(s) - i
            i = j + 1
            continue
        out += 1
        i += 1
    return out


def _pad(s: str, width: int, right_align: bool) -> str:
    gap = max(0, width - _visible_len(s))
    return (" " * gap + s) if right_align else (s + " " * gap)


def _cell(
    row: Row,
    col: str,
    use_color: bool,
    position_widths: list[int] | None = None,
) -> str:
    v = getattr(row, _row_attr(col))
    if col in HISTORICAL_COLUMNS:
        return _fmt_history_cell(
            v,
            col,
            use_color,
            position_widths,
            row.protocol,
        )
    if col == "timeouts":
        return _fmt_num(v)
    if col == "battery":
        return _fmt_battery(v)
    if col == "last-seen":
        return _fmt_last_seen(v)
    if col == "route-speed":
        return _fmt_route_speed(v)
    if col == "max-speed":
        return _fmt_max_speed(v)
    if col == "role":
        return _fmt_role(v)
    if col == "neighbors":
        return _fmt_neighbors(v)
    if col in ("firmware-dev", "firmware-sdk"):
        return _fmt_version(v)
    if col == "node":
        return str(v)
    if v is None or v == "":
        return DASH
    return str(v)


def _history_position_widths(
    rows: list[Row],
    col: str,
) -> list[int]:
    """Max visible width per list-position for a historical column.

    Used to vertically align sub-values across rows so the
    "1 day ago", "2 days ago" slots line up even when a row
    has a null (``-``) latest value that's narrower than the
    other values.
    """
    widths: list[int] = []
    attr = _row_attr(col)
    for r in rows:
        v = getattr(r, attr)
        if not isinstance(v, list):
            continue
        protocol = r.protocol
        for i, item in enumerate(v):
            # color=False avoids emitting throwaway colored
            # strings during width calculation (_visible_len
            # would strip the codes anyway).
            s = _fmt_history_sub(item, col, False, protocol)
            if i >= len(widths):
                widths.append(0)
            widths[i] = max(widths[i], _visible_len(s))
    return widths


def _format_table(
    header_cells: list[str],
    data_cells: list[list[str]],
    right_align: list[bool],
    *,
    show_header: bool,
) -> str:
    """Lay out a header + pre-rendered string cells into an aligned,
    space-padded table. Column-agnostic, so every table view (``list`` plus
    the param-manager views) shares one layout."""

    widths = [_visible_len(h) for h in header_cells]
    for row_cells in data_cells:
        for i, c in enumerate(row_cells):
            widths[i] = max(widths[i], _visible_len(c))

    lines: list[str] = []
    if show_header:
        lines.append(
            "  ".join(
                _pad(header_cells[i], widths[i], right_align=False)
                for i in range(len(header_cells))
            ),
        )
        lines.append("  ".join("-" * w for w in widths))
    for row_cells in data_cells:
        lines.append(
            "  ".join(
                _pad(row_cells[i], widths[i], right_align[i])
                for i in range(len(row_cells))
            ),
        )
    return "\n".join(lines)


def render_table(
    rows: list[Row],
    columns: list[str],
    use_color: bool,
    show_header: bool = True,
) -> str:
    header_cells = [_COLUMN_HEADERS[c] for c in columns]
    position_widths_by_col = {
        c: _history_position_widths(rows, c)
        for c in columns
        if c in HISTORICAL_COLUMNS
    }
    data_cells: list[list[str]] = [
        [_cell(r, c, use_color, position_widths_by_col.get(c)) for c in columns]
        for r in rows
    ]
    right_align = [c in _CELL_RIGHT_ALIGNED for c in columns]
    return _format_table(
        header_cells, data_cells, right_align, show_header=show_header
    )


# --- Sorting ----------------------------------------------------


def _sort_value(row: Row, col: str) -> Any:
    """Return the sort key for ``col`` on ``row`` (or ``None``).

    Numeric columns sort by raw value ascending (e.g. ``--sort ss``
    puts weakest/most-negative first -- usually the problem nodes
    you want to spot). Historical columns sort on their latest
    (leftmost) value. Nulls are handled by ``_sort_rows``.
    """
    v = getattr(row, _row_attr(col))
    if col in HISTORICAL_COLUMNS:
        v = v[0] if isinstance(v, list) else v
    if v is None:
        return None
    # Columns whose stored value doesn't sort intuitively on
    # its own get a dedicated key.
    if col == "neighbors":
        return len(v) if isinstance(v, list) else None
    if col == "role":
        return ZWAVE_PLUS_ROLES.get(v, f"?{v}") if isinstance(v, int) else None
    if col == "ss-quality":
        # Severity ascending so `--sort ss-quality` surfaces
        # the problem nodes at the top.
        return {"poor": 0, "fair": 1, "good": 2}.get(v, 99)
    if isinstance(v, str):
        return v.lower()
    return v


def _sort_rows(
    rows: list[Row],
    cols: list[str],
    reverse: bool,
) -> list[Row]:
    """Multi-column stable sort.

    ``cols`` is the priority-ordered list of sort keys --
    primary first. Rows whose *primary* key is ``None`` are
    always grouped at the end of the output regardless of
    ``--reverse``; nulls in secondary keys sort via the usual
    Python tuple comparison (the ``is_null`` flag in each
    tuple position sends them to the tail within their group).
    """
    if not cols:
        return list(rows)
    primary = cols[0]
    with_primary: list[Row] = []
    without_primary: list[Row] = []
    for r in rows:
        (
            with_primary
            if _sort_value(r, primary) is not None
            else without_primary
        ).append(r)

    def key_fn(r: Row) -> tuple[tuple[int, Any], ...]:
        parts: list[tuple[int, Any]] = []
        for col in cols:
            v = _sort_value(r, col)
            # (is_null_flag, value_or_placeholder). The null flag
            # keeps None tuples from being compared on value and
            # sorts them after non-nulls within a column group.
            parts.append((1, 0) if v is None else (0, v))
        return tuple(parts)

    with_primary.sort(key=key_fn, reverse=reverse)
    return with_primary + without_primary


def _parse_sort(raw: str) -> list[str]:
    """Parse ``--sort`` into an ordered list of column keys.

    Accepts a comma-separated list (e.g. ``location,device``).
    Each key must be one of ``ALL_COLUMNS``. Duplicates are
    dropped (first wins).
    """
    cols: list[str] = []
    for c in raw.split(","):
        k = c.strip().lower()
        if not k:
            continue
        if k not in ALL_COLUMNS:
            raise SystemExit(
                f"--sort: unknown column {k!r}. "
                f"Must be one of: {', '.join(ALL_COLUMNS)}",
            )
        if k not in cols:
            cols.append(k)
    return cols or ["node"]


# --- Column parsing ---------------------------------------------


def _parse_columns(cols: str) -> list[str]:
    """Resolve the ordered display column list.

    The ``--cols`` value is a comma-separated list of column
    names and aliases. Aliases come from ``_COLUMN_ALIASES``
    (e.g. ``defaults``, ``firmware`` -> expands to firmware-dev +
    firmware-sdk) plus the special ``all``. Real column names
    can be mixed freely with aliases.

    Examples: ``--cols defaults,rtt``, ``--cols all``,
    ``--cols node,device,firmware``. Duplicates are dropped
    (first wins, preserving order).
    """
    if not cols:
        return list(_COLUMN_ALIASES["defaults"])
    picked: list[str] = []
    for raw in cols.split(","):
        key = raw.strip().lower()
        if not key:
            continue
        if key == "all":
            return list(ALL_COLUMNS)
        if key in _COLUMN_ALIASES:
            for c in _COLUMN_ALIASES[key]:
                if c not in picked:
                    picked.append(c)
            continue
        if key not in ALL_COLUMNS:
            alias_list = ", ".join(sorted(_COLUMN_ALIASES.keys()))
            raise SystemExit(
                f"--cols: unknown column {key!r}. "
                f"Known aliases: all, {alias_list}. "
                f"Known columns: {', '.join(ALL_COLUMNS)}",
            )
        if key not in picked:
            picked.append(key)
    return picked if picked else list(_COLUMN_ALIASES["defaults"])


# --- Orchestration ----------------------------------------------


async def _run(
    api_key: str,
    day_offsets: list[int],
    columns: list[str],
    use_snapshot_data: bool = False,
) -> tuple[
    dict[int, ZwaveNode],
    dict[int, NodeHaInfo],
    dict[str, str],
    dict[str, dict[int, str]],
    dict[int, list[int]],
]:
    """Fetch everything in parallel where possible.

    Only fetch history for entities that correspond to columns
    we're actually going to display -- saves queries when the
    user runs with a pared-down ``--cols``. Neighbors require a
    separate API call per node, so they're only fetched when
    the ``neighbors`` column is requested.
    """
    zwave_task = asyncio.create_task(
        fetch_zwave_nodes(use_snapshot_data=use_snapshot_data),
    )
    reg_task = asyncio.create_task(fetch_ha_registries(api_key))
    states_task = asyncio.create_task(fetch_ha_states(api_key))

    zwave_nodes = await zwave_task
    entities, devices_by_id, areas_by_id = await reg_task
    current_states = await states_task

    node_to_ha = build_node_to_ha(devices_by_id, areas_by_id, entities)

    # Expand derived rate columns to their source counter cols
    # so we fetch the underlying HA sensor history. A column like
    # ``rx-drop-rate`` has no entity of its own -- it needs
    # ``rx`` + ``rx-drop`` history to be computed row-by-row.
    historical_cols_to_fetch: list[str] = []
    for c in columns:
        if c not in HISTORICAL_COLUMNS:
            continue
        if c in _RATE_COLUMNS:
            historical_cols_to_fetch.extend(_RATE_COLUMNS[c])
        else:
            historical_cols_to_fetch.append(c)

    needed_entity_ids: list[str] = []
    for info in node_to_ha.values():
        for col in historical_cols_to_fetch:
            eid = info.stat_entities.get(col)
            if eid:
                needed_entity_ids.append(eid)
    needed_entity_ids = sorted(set(needed_entity_ids))

    history: dict[str, dict[int, str]] = {}
    neighbors: dict[int, list[int]] = {}

    hist_task = None
    if day_offsets and needed_entity_ids:
        hist_task = asyncio.create_task(
            fetch_ha_history(api_key, needed_entity_ids, day_offsets),
        )
    neigh_task = None
    if "neighbors" in columns:
        # Skip the controller -- the caller filters it out anyway.
        neigh_task = asyncio.create_task(
            fetch_zwave_neighbors(
                [nid for nid in zwave_nodes if nid != 1],
            ),
        )
    if hist_task is not None:
        history = await hist_task
    if neigh_task is not None:
        neighbors = await neigh_task

    return zwave_nodes, node_to_ha, current_states, history, neighbors


def _add_list_args(parser: argparse.ArgumentParser) -> None:
    """Attach the per-node network-view flags to the ``list`` subparser."""

    parser.add_argument(
        "--cols",
        default="",
        help=(
            "comma-separated ordered list of columns to display. "
            "Accepts column names and aliases -- see the Columns "
            "sections below."
        ),
    )
    parser.add_argument(
        "--days",
        type=int,
        default=0,
        help=(
            "number of past days to fetch per historical stat "
            "(default: 0 = latest value only). Must be <= HA's "
            "recorder.purge_keep_days."
        ),
    )
    parser.add_argument(
        "--sort",
        default="node",
        metavar="COLS",
        help=(
            "comma-separated ordered list of columns to sort "
            "by (primary first). See the Columns sections below."
        ),
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="reverse sort order",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="suppress the header row and divider",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI color output",
    )
    parser.add_argument(
        "--use-snapshot-data",
        action="store_true",
        help=(
            "skip the per-node route refresh and use the bulk "
            "getNodes() snapshot values for priority-route "
            "and SUC-return-route fields. Those values may be "
            "stale (the snapshot is only updated on route "
            "assignment or driver startup). Use when the "
            "controller can't service the live queries and "
            "some data is better than none."
        ),
    )


def do_list(
    *,
    cols: str,
    days: int,
    sort: str,
    reverse: bool,
    no_header: bool,
    no_color: bool,
    use_snapshot_data: bool,
) -> int:
    """Render the per-node network table (the ``list`` subcommand)."""

    if days < 0:
        print("error: --days must be >= 0", file=sys.stderr)
        return 2
    if days > 0:
        keep = _read_recorder_keep_days()
        if days > keep:
            print(
                f"error: --days {days} exceeds HA's "
                f"recorder.purge_keep_days ({keep}). "
                f"Reduce --days or increase purge_keep_days "
                f"in HA's configuration.yaml.",
                file=sys.stderr,
            )
            return 2
    day_offsets = list(range(1, days + 1))

    columns = _parse_columns(cols)

    if not API_KEY_FILE.exists():
        print(f"API key file not found: {API_KEY_FILE}", file=sys.stderr)
        return 2
    api_key = API_KEY_FILE.read_text().strip()

    # socketio.exceptions.TimeoutError is a distinct class from
    # the builtin TimeoutError -- catch both so a wedged Z-Wave
    # controller produces a clear message instead of a traceback.
    # ZwaveApiError covers the "addon is up but driver can't
    # service calls" state (e.g. ``"Z-Wave client not
    # connected"`` while zwave-js loops on controller init).
    # Keep this local: the dependency is installed only in the
    # bootstrapped script venv after re-exec.
    import socketio.exceptions as _sio_exc

    try:
        (
            zwave_nodes,
            node_to_ha,
            current_states,
            history,
            neighbors,
        ) = asyncio.run(
            _run(
                api_key,
                day_offsets,
                columns,
                use_snapshot_data=use_snapshot_data,
            ),
        )
    except (TimeoutError, _sio_exc.TimeoutError) as e:
        detail = str(e) or type(e).__name__
        print(
            f"Error: Z-Wave query timed out: {detail}",
            file=sys.stderr,
        )
        print(
            "The Z-Wave controller is unresponsive to API queries. "
            "Re-run with --use-snapshot-data to fall back to the "
            "bulk getNodes() snapshot (values may be stale).",
            file=sys.stderr,
        )
        return 3
    except ZwaveApiError as e:
        # --use-snapshot-data also calls getNodes, so if the
        # envelope says the driver isn't connected there's no
        # fallback to offer here -- just surface the error.
        print(f"Error: Z-Wave API call failed: {e}", file=sys.stderr)
        print(
            "The Z-Wave JS addon is running but its driver "
            "is not connected to the controller. Check the "
            "Z-Wave JS addon logs; a stuck controller may "
            "need an addon restart or a host reboot to clear.",
            file=sys.stderr,
        )
        return 4
    rows = build_rows(
        zwave_nodes,
        node_to_ha,
        current_states,
        history,
        day_offsets,
        neighbors,
    )
    rows = _sort_rows(rows, _parse_sort(sort), reverse=reverse)

    use_color = (not no_color) and sys.stdout.isatty()
    print(render_table(rows, columns, use_color, show_header=not no_header))
    return 0


# --- Parameter Manager: shared read via a standalone access layer ---
# zwavectl runs the same read + planner as the ZPM handler, only from a
# different access layer: the handler reuses HA's in-process zwave-js client
# and registries; this CLI opens its own zwave-js-server socket and reads the
# HA registries / states over the API. Both feed the integration's shared
# `source.build_node_read`, so the CLI resolves and reports identically.


class _FleetReadError(Exception):
    """A transport failure while reading the param-manager fleet (the 3000
    socket or the HA API), surfaced as a clear message, not a traceback."""


def _ensure_integration_importable() -> None:
    """Put the integration's package root on sys.path so the shared
    ``blueprint_toolkit.zwave_parameter_manager`` modules import.

    zwavectl ships inside the integration tree but runs standalone, so it puts
    ``custom_components`` (the dir holding the ``blueprint_toolkit`` package) on
    sys.path. ``resolve()`` follows a cli-symlink to the real bundled file so
    the walk is correct through a $PATH symlink. Callers then import under the
    ``blueprint_toolkit`` top-level name -- the name HA's loader and mypy both
    use for the package -- so the static import type-checks. Deferred to the
    param-manager views, so ``list`` stays dependency-free.
    """

    cc_dir = str(pathlib.Path(__file__).resolve().parents[3])
    if cc_dir not in sys.path:
        sys.path.insert(0, cc_dir)


async def _fetch_zwave_server_nodes() -> list[dict[str, Any]]:
    """The zwave-js server's live per-node state via one start_listening.

    Raw websocket to 3000; the node dicts carry the value metadata the param
    resolver needs (which the 8091 getNodes() snapshot omits).
    """

    import websockets  # noqa: PLC0415 - needs venv
    from zwave_js_server.const import (  # noqa: PLC0415 - needs venv
        MAX_SERVER_SCHEMA_VERSION,
    )

    async with websockets.connect(ZWAVE_SERVER_URL, max_size=None) as ws:

        async def recv() -> ServerMessage:
            return cast(
                "ServerMessage",
                json.loads(
                    await asyncio.wait_for(ws.recv(), ZWAVE_SERVER_RECV_TIMEOUT)
                ),
            )

        hello = await recv()
        schema = min(
            int(hello.get("maxSchemaVersion", 1)), MAX_SERVER_SCHEMA_VERSION
        )
        await ws.send(
            json.dumps(
                {
                    "messageId": "sv",
                    "command": "set_api_schema",
                    "schemaVersion": schema,
                }
            )
        )
        while (await recv()).get("messageId") != "sv":
            pass
        await ws.send(
            json.dumps({"messageId": "sl", "command": "start_listening"})
        )
        while True:
            msg = await recv()
            if msg.get("messageId") == "sl":
                nodes: list[dict[str, Any]] = msg["result"]["state"]["nodes"]
                return nodes


async def _fetch_state_device_classes(api_key: str) -> dict[str, str | None]:
    """``entity_id -> device_class`` off the live state attributes.

    zwave_js publishes the device class on the entity's state, not the
    registry, so device-type derivation reads it from the state (mirrors the
    handler's ``source._device_class`` fallback).
    """

    import aiohttp  # noqa: PLC0415 - needs venv

    headers = {"Authorization": f"Bearer {api_key}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{HA_URL}/api/states", headers=headers) as r:
            r.raise_for_status()
            states = cast("list[HaState]", await r.json())
    return {
        s["entity_id"]: s.get("attributes", {}).get("device_class")
        for s in states
    }


@dataclass(frozen=True)
class NodeContext:
    """The HA context ``source.build_node_read`` needs for one node, parsed
    out of the registries: ``device_id`` / display ``name`` / ``location`` and
    each entity's ``(domain, device_class)`` (state device_class fallback).
    Field names + types mirror ``build_node_read``'s keyword parameters."""

    device_id: str | None
    name: str
    location: str | None
    entities: list[tuple[str, str | None]]


def _node_contexts(
    devices_by_id: dict[str, DeviceRow],
    entities: list[EntityRow],
    areas_by_id: dict[str, AreaRow],
    device_classes: dict[str, str | None],
) -> dict[int, NodeContext]:
    """Map each zwave node_id to its ``NodeContext``."""

    dev_to_node = node_ids_by_device(devices_by_id)

    names: dict[int, str] = {}
    locations: dict[int, str | None] = {}
    ents: dict[int, list[tuple[str, str | None]]] = {}
    for dev_id, node_id in dev_to_node.items():
        dev = devices_by_id[dev_id]
        area_id = dev.get("area_id")
        locations[node_id] = (
            areas_by_id[area_id].get("name")
            if area_id and area_id in areas_by_id
            else None
        )
        names[node_id] = dev.get("name_by_user") or dev.get("name") or ""
        ents[node_id] = []

    for ent in entities:
        if ent.get("platform") != "zwave_js":
            continue
        nid = dev_to_node.get(ent.get("device_id") or "")
        if nid is None:
            continue
        eid = ent.get("entity_id") or ""
        dclass = (
            ent.get("device_class")
            or ent.get("original_device_class")
            or device_classes.get(eid)
        )
        ents[nid].append((eid.split(".", 1)[0], dclass))

    return {
        node_id: NodeContext(
            device_id=dev_id,
            name=names[node_id],
            location=locations[node_id],
            entities=ents[node_id],
        )
        for dev_id, node_id in dev_to_node.items()
    }


def _assemble_fleet(
    node_dicts: list[dict[str, Any]],
    contexts: dict[int, NodeContext],
) -> list[NodeRead]:
    """Each live node dict + its HA context through the shared
    ``source.build_node_read``. Returns a list of ``NodeRead``."""

    _ensure_integration_importable()
    from blueprint_toolkit.zwave_parameter_manager.source import (  # noqa: PLC0415
        build_node_read,
    )
    from zwave_js_server.client import Client  # noqa: PLC0415 - needs venv
    from zwave_js_server.model.node import Node  # noqa: PLC0415 - needs venv
    from zwave_js_server.model.node.data_model import (  # noqa: PLC0415
        NodeDataType,
    )

    fleet: list[NodeRead] = []
    for data in node_dicts:
        # We only read values off the node; the client is never touched, so a
        # cast supplies the read-only construction without a live Client.
        node = Node(cast(Client, None), cast(NodeDataType, data))
        ctx = contexts.get(node.node_id)
        fleet.append(
            build_node_read(
                node,
                device_id=ctx.device_id if ctx else None,
                name=(ctx.name if ctx else "") or node.name or "",
                location=ctx.location if ctx else None,
                entities=ctx.entities if ctx else [],
                last_awake=None,
            )
        )
    return fleet


async def _read_param_manager_fleet(api_key: str) -> list[NodeRead]:
    """Acquire and assemble the param-manager fleet from the live sources."""

    node_dicts = await _fetch_zwave_server_nodes()
    entities, devices_by_id, areas_by_id = await fetch_ha_registries(api_key)
    device_classes = await _fetch_state_device_classes(api_key)
    contexts = _node_contexts(
        devices_by_id, entities, areas_by_id, device_classes
    )
    return _assemble_fleet(node_dicts, contexts)


@dataclass(frozen=True)
class _PmRow:
    """One param-manager table row for the ``desired`` / ``pending`` views.

    ``device`` is the report's wake-context device, ``param`` its rendered
    desired-vs-actual row (generic + device views), ``write`` the planned write
    behind it (the raw target + ``Device`` make/model/power/types + ``ParamId``)
    and ``raw_current`` the live raw value off the fleet -- the union of
    everything any column can show.
    """

    device: ConvergenceDevice
    param: ParamConvergence
    write: PlannedWrite | None
    raw_current: int | None


@dataclass(frozen=True)
class _PmCol:
    """A param-manager column: header, a row -> cell-string extractor, and
    whether it right-aligns (numeric)."""

    header: str
    extract: Callable[[_PmRow], str]
    right: bool = False


def _pm_policy(r: _PmRow) -> str:
    return r.write.policy if r.write is not None else ""


def _pm_device_type(r: _PmRow) -> str:
    if r.write is None:
        return ""
    return ",".join(sorted(str(t) for t in r.write.device.device_types))


def _pm_make(r: _PmRow) -> str:
    return r.write.device.manufacturer if r.write is not None else ""


def _pm_model(r: _PmRow) -> str:
    return r.write.device.model if r.write is not None else ""


def _pm_power(r: _PmRow) -> str:
    if r.write is None:
        return ""
    return "Mains" if r.write.device.is_listening else "Battery"


def _pm_command_class(r: _PmRow) -> str:
    return str(r.write.id.command_class) if r.write is not None else ""


def _pm_property(r: _PmRow) -> str:
    return str(r.write.id.property_) if r.write is not None else ""


def _pm_property_key(r: _PmRow) -> str:
    if r.write is None or r.write.id.property_key is None:
        return ""
    return str(r.write.id.property_key)


def _pm_property_pending(r: _PmRow) -> str:
    return str(r.write.value) if r.write is not None else ""


def _pm_property_current(r: _PmRow) -> str:
    return "" if r.raw_current is None else str(r.raw_current)


# ``parameter`` / ``desired`` / ``current`` are the generic concept view;
# the device-specific raw values are the optional ``property-*`` columns.
_PM_COLUMNS: dict[str, _PmCol] = {
    "node": _PmCol("node", lambda r: str(r.device.node_id), right=True),
    "device": _PmCol("device", lambda r: r.device.name),
    "location": _PmCol("location", lambda r: r.device.location or ""),
    "parameter": _PmCol("parameter", lambda r: r.param.concept),
    "desired": _PmCol("desired", lambda r: r.param.concept_desired),
    "current": _PmCol("current", lambda r: r.param.actual or ""),
    "policy": _PmCol("policy", _pm_policy),
    "device-type": _PmCol("device-type", _pm_device_type),
    "make": _PmCol("make", _pm_make),
    "model": _PmCol("model", _pm_model),
    "power": _PmCol("power", _pm_power),
    "command-class": _PmCol("command-class", _pm_command_class, right=True),
    "property": _PmCol("property", _pm_property),
    "property-key": _PmCol("property-key", _pm_property_key, right=True),
    "property-pending": _PmCol(
        "property-pending", _pm_property_pending, right=True
    ),
    "property-current": _PmCol(
        "property-current", _pm_property_current, right=True
    ),
}

_PM_DESIRED_COLS = [
    "node",
    "device",
    "location",
    "parameter",
    "desired",
    "policy",
]
_PM_PENDING_COLS = [
    "node",
    "device",
    "location",
    "parameter",
    "desired",
    "current",
    "policy",
]

# Generated from the registry so the --cols help can never drift from the
# columns _pm_parse_cols actually accepts. Both views accept any registry
# column; only the default set differs.
_PM_COLS_HELP = (
    "comma-separated ordered columns. Default for desired: "
    f"{','.join(_PM_DESIRED_COLS)}; for pending: "
    f"{','.join(_PM_PENDING_COLS)}. Available: "
    f"{', '.join(_PM_COLUMNS)}."
)


def _pm_parse_cols(
    spec: str, default: list[str]
) -> tuple[list[str], str | None]:
    """A ``--cols`` spec -> ordered column list (``default`` when the spec
    names no columns, i.e. empty or only separators / whitespace), or
    ``([], error)`` when a name is unknown."""

    cols = [c.strip() for c in spec.split(",") if c.strip()]
    if not cols:
        return list(default), None
    unknown = [c for c in cols if c not in _PM_COLUMNS]
    if unknown:
        return [], f"unknown column(s): {', '.join(unknown)}"
    return cols, None


def _pm_write_rows(
    report: ConvergenceReport,
    plan: Plan,
    fleet: list[NodeRead],
    *,
    pending: bool,
) -> list[_PmRow]:
    """Assemble ``_PmRow`` objects for the ``desired`` (all) or ``pending``
    (non-converged) writes, joining the report rows to their planned write +
    live raw value by ``(node_id, concept)`` / ``(node_id, ParamId)``."""

    write_by = {(w.device.node_id, str(w.concept)): w for w in plan.writes}
    actuals_by = {
        (rd.device.node_id, pid): v
        for rd in fleet
        for pid, v in rd.actuals.items()
    }
    devices = report.pending_devices if pending else report.devices
    rows: list[_PmRow] = []
    for dc in devices:
        params = dc.pending_params if pending else dc.params
        for p in params:
            write = write_by.get((dc.device.node_id, p.concept))
            raw = (
                actuals_by.get((dc.device.node_id, write.id))
                if write is not None
                else None
            )
            rows.append(
                _PmRow(device=dc.device, param=p, write=write, raw_current=raw)
            )
    return rows


def _pm_write_table(
    rows: list[_PmRow], columns: list[str], *, show_header: bool = True
) -> str:
    cols = [_PM_COLUMNS[c] for c in columns]
    headers = [c.header for c in cols]
    right = [c.right for c in cols]
    data = [[c.extract(r) for c in cols] for r in rows]
    return _format_table(headers, data, right, show_header=show_header)


def _pm_unused_table(plan: Plan, *, show_header: bool = True) -> str:
    """The ``unused`` view: configured policies / settings that landed on no
    device. ``parameter`` is the inert setting, or ``-`` when the whole policy
    matched nothing; ``reason`` is the explanation."""

    headers = ["policy", "parameter", "reason"]
    right_align = [False, False, False]
    data: list[list[str]] = [
        [
            u.policy,
            "-" if u.concept is None else str(u.concept),
            u.reason,
        ]
        for u in plan.unused
    ]
    return _format_table(headers, data, right_align, show_header=show_header)


def _param_manager_config(
    mode: str,
    *,
    config: str = "",
    cols: str = "",
    no_header: bool = False,
) -> int:
    """Plan the live fleet against the policy file and render the ``mode``
    view. Reads the fleet via this CLI's own access layer feeding the shared
    ``build_node_read`` -- the same convergence the ZPM handler computes."""

    config_path = pathlib.Path(config) if config else PM_CONFIG_DEFAULT
    default_cols = _PM_PENDING_COLS if mode == "pending" else _PM_DESIRED_COLS
    columns, cols_err = _pm_parse_cols(cols, default_cols)
    if cols_err is not None:
        print(f"Error: {cols_err}", file=sys.stderr)
        return 2

    if not API_KEY_FILE.exists():
        print(f"API key file not found: {API_KEY_FILE}", file=sys.stderr)
        return 2
    api_key = API_KEY_FILE.read_text().strip()

    if not config_path.exists():
        print(f"Policy file not found: {config_path}", file=sys.stderr)
        return 2

    _ensure_integration_importable()
    from blueprint_toolkit.zwave_parameter_manager import (  # noqa: PLC0415
        pipeline,
    )

    policies, config_errors = pipeline.load_policies(config_path)
    if config_errors:
        print("Policy config errors:", file=sys.stderr)
        for err in config_errors:
            print(f"  - {err}", file=sys.stderr)
        return 2
    mapping, mapping_err = pipeline.load_mapping()
    if mapping is None:
        print(f"Error loading mapping: {mapping_err}", file=sys.stderr)
        return 2

    try:
        fleet = _read_param_manager_fleet_sync(api_key)
    except _FleetReadError as e:
        print(f"Error: could not read the Z-Wave fleet: {e}", file=sys.stderr)
        print(
            "Check that the Z-Wave JS add-on is running, the zwave-js server "
            "is reachable on 3000, and the API key is valid.",
            file=sys.stderr,
        )
        return 4

    plan, report = pipeline.plan_and_report(fleet, policies, mapping)
    show_header = not no_header

    if mode == "unused":
        print(_pm_unused_table(plan, show_header=show_header))
        return 0
    rows = _pm_write_rows(report, plan, fleet, pending=mode == "pending")
    print(_pm_write_table(rows, columns, show_header=show_header))
    return 0


def _read_param_manager_fleet_sync(api_key: str) -> list[NodeRead]:
    """The async fleet read, run to completion; transport failures (the 3000
    socket or the HA API) surface as ``_FleetReadError`` so the caller prints
    a clear message instead of a traceback."""

    import aiohttp  # noqa: PLC0415 - needs venv
    import websockets.exceptions as ws_exc  # noqa: PLC0415 - needs venv

    try:
        return asyncio.run(_read_param_manager_fleet(api_key))
    except (
        TimeoutError,
        OSError,
        RuntimeError,
        aiohttp.ClientError,
        ws_exc.WebSocketException,
        # A malformed server frame: a bad JSON payload (ValueError, which
        # json.JSONDecodeError subclasses) or a missing expected key.
        ValueError,
        KeyError,
    ) as e:
        raise _FleetReadError(str(e) or type(e).__name__) from e


def do_pm_config_desired(*, config: str, cols: str, no_header: bool) -> int:
    return _param_manager_config(
        "desired", config=config, cols=cols, no_header=no_header
    )


def do_pm_config_pending(*, config: str, cols: str, no_header: bool) -> int:
    return _param_manager_config(
        "pending", config=config, cols=cols, no_header=no_header
    )


def do_pm_config_unused(*, config: str, no_header: bool) -> int:
    return _param_manager_config("unused", config=config, no_header=no_header)


# --- Argparse: strict subparsers + auto-help on a missing action ----
# Inlined from epilatow/utils ``src/common/argparse_ext.py`` -- this script
# ships standalone to the HA host and cannot import shared first-party code.

if TYPE_CHECKING:
    # Imported under the ``blueprint_toolkit`` top-level name -- the name HA's
    # loader and mypy both use for the package (``custom_components`` carries
    # no ``__init__``) -- so the type resolves to the real dataclass instead of
    # colliding under a second module name. ``_assemble_fleet`` imports the
    # callables the same way at runtime (after putting the package root on
    # sys.path).
    from blueprint_toolkit.zwave.convergence import (
        ConvergenceDevice,
        ConvergenceReport,
        ParamConvergence,
    )
    from blueprint_toolkit.zwave_parameter_manager.logic import (
        Plan,
        PlannedWrite,
    )
    from blueprint_toolkit.zwave_parameter_manager.source import NodeRead

    _SubParsersActionBase = argparse._SubParsersAction[argparse.ArgumentParser]
else:
    _SubParsersActionBase = argparse._SubParsersAction  # noqa: SLF001


class _StrictSubParsersAction(_SubParsersActionBase):
    """Route a subparser's argument errors through that subparser, not the
    root, so the error names the subcommand the user actually typed.

    Stdlib stashes leftover subcommand tokens on the top-level namespace, so
    an unknown-arg error is reported by the root parser with its usage line;
    calling the chosen subparser's strict ``parse_args`` instead routes the
    error through that subparser's own ``error()``.
    """

    def __call__(
        self,
        _parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        _option_string: str | None = None,
    ) -> None:
        parser_name = values[0]
        arg_strings = values[1:]
        if self.dest is not argparse.SUPPRESS:
            setattr(namespace, self.dest, parser_name)
        subparser = self._name_parser_map[parser_name]  # noqa: SLF001
        subnamespace = subparser.parse_args(arg_strings)
        for key, value in vars(subnamespace).items():
            setattr(namespace, key, value)


class _StrictArgumentParser(argparse.ArgumentParser):
    """ArgumentParser whose subparsers use the strict action above; child
    parsers inherit it (add_subparsers defaults parser_class to type(self))."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.register("action", "parsers", _StrictSubParsersAction)

    def parse_command(
        self, argv: list[str] | None = None
    ) -> argparse.Namespace:
        """Parse argv and collapse the numbered ``cmd<level>`` dests into a
        single ``command`` path (space-joined), leaving only the leaf's own
        options on the namespace.

        A path that stops at an action group (no command, or an action group
        entered with no action chosen) prints the deepest level's help and
        exits 2 -- the same way argparse exits for ``-h`` or a usage error,
        but with the subcommand's full help rather than a terse usage line.
        Invalid arguments / subcommands are still ``parse_args``'s usual
        usage error.
        """

        data = vars(self.parse_args(argv))
        action_help = data.pop("_action_help", None)
        path: list[str] = []
        level = 1
        while f"cmd{level}" in data:
            chosen = data.pop(f"cmd{level}")
            if chosen is None:
                help_fn = action_help or self.print_help
                help_fn()
                raise SystemExit(2)
            path.append(chosen)
            level += 1
        return argparse.Namespace(command=" ".join(path), **data)


def _action_subparsers(
    parent: argparse.ArgumentParser, *, level: int, **kwargs: Any
) -> _SubParsersActionBase:
    """Add a subparsers group to ``parent`` under the generic ``cmd<level>``
    dest, recording ``parent.print_help`` as the ``_action_help`` default so
    an omitted action prints the parent's own help (invoked by ``cli``).

    Levels are numbered, not named, so every nesting depth shares one dest
    scheme (cmd1, cmd2, ...) that ``cli`` walks generically -- a new
    subcommand at any depth needs no new per-command dest name.
    """

    parent.set_defaults(_action_help=parent.print_help)
    return parent.add_subparsers(dest=f"cmd{level}", **kwargs)


def build_parser() -> _StrictArgumentParser:
    """Build the command tree: ``list`` (the network view) and ``param-manager
    config {desired|pending|unused}`` (the Parameter Manager views).

    Action groups are added via ``_action_subparsers`` so ``cli`` can dispatch
    and print help generically.
    """

    parser = _StrictArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd1", metavar="COMMAND")

    list_parser = sub.add_parser(
        "list",
        help="per-node Z-Wave network view",
        description=__doc__,
        epilog=_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_list_args(list_parser)

    pm_parser = sub.add_parser(
        "param-manager",
        help="Z-Wave Parameter Manager views",
    )
    pm_sub = _action_subparsers(pm_parser, level=2)

    config_parser = pm_sub.add_parser(
        "config",
        help="show the desired / pending / unused parameter config",
    )
    config_sub = _action_subparsers(config_parser, level=3)
    _add_pm_config_args(
        config_sub.add_parser(
            "desired",
            help="every device + param a policy resolves a write for",
        ),
        with_cols=True,
    )
    _add_pm_config_args(
        config_sub.add_parser(
            "pending", help="only the not-yet-converged device + params"
        ),
        with_cols=True,
    )
    _add_pm_config_args(
        config_sub.add_parser(
            "unused", help="policies / settings that match no device"
        ),
        with_cols=False,
    )
    return parser


def _add_pm_config_args(
    parser: argparse.ArgumentParser, *, with_cols: bool
) -> None:
    """Attach the shared param-manager-config flags. ``--cols`` only applies
    to the column-selectable views (``desired`` / ``pending``)."""

    parser.add_argument(
        "--config",
        default="",
        metavar="PATH",
        help=(
            "policy file to plan against "
            "(default: /config/zwave_parameter_manager.yaml)"
        ),
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="omit the table header row",
    )
    if with_cols:
        parser.add_argument("--cols", default="", help=_PM_COLS_HELP)


COMMAND_CALLBACKS: dict[str, Callable[..., int]] = {
    "list": do_list,
    "param-manager config desired": do_pm_config_desired,
    "param-manager config pending": do_pm_config_pending,
    "param-manager config unused": do_pm_config_unused,
}


def cli() -> int:
    """Parse argv and dispatch to the matching COMMAND_CALLBACKS entry.

    ``parse_command`` resolves the numbered subcommand levels into ``command``
    (and prints help + exits for a missing subcommand); the leaf's own options
    pass through to the callback as keyword arguments.
    """

    args = vars(build_parser().parse_command())
    return COMMAND_CALLBACKS[args.pop("command")](**args)


if __name__ == "__main__":
    bootstrap_venv()
    reexec_in_venv()
    sys.exit(cli())
