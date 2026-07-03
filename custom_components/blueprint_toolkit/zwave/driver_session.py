# This is AI generated code
"""Shared Z-Wave JS driver-session record.

The Z-Wave JS driver holds each sleeping device's queued commands in an
in-memory wake-up queue that is flushed when the driver (the ``core_zwave_js``
add-on) restarts. The zwave-js-server state exposes no driver-start timestamp,
but the controller-statistics counters (messages rx / tx) reset to zero on a
restart -- so a live counter BELOW a previously-recorded value means the driver
restarted and the queue was flushed.

This module owns ``zwave-js-info.json`` under the HA config dir: the last-seen
counters plus ``last_reset_at`` (when a reset was last detected). The
integration's always-on monitor refreshes it every minute, and the CLI
refreshes it at apply time; both the ZPM handler and (later) ZRM read
``last_reset_at`` to decide whether their issued-but-unconverged writes were
flushed. Comparing against a recorded RESET TIME rather than a self-sampled
counter is what lets a sparse consumer (the CLI run every few days) still see a
restart the counter has since climbed back past.

Pure file I/O -- no HA imports -- so the CLI venv imports it too.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from . import atomic_json

if TYPE_CHECKING:
    from pathlib import Path

# Location of the shared record, relative to the HA config dir. The CLI's
# default resolves to the same absolute path under /config.
INFO_REL_PATH = "blueprint_toolkit/zwave-js-info.json"


@dataclass(frozen=True)
class DriverSession:
    """The persisted driver-session record.

    ``last_reset_at`` is the authoritative signal for consumers: any write
    issued before it was flushed by a driver restart. ``messages_rx`` /
    ``messages_tx`` are the last-seen counters used to detect the next reset;
    ``updated_at`` is when the record was last refreshed.
    """

    home_id: int
    messages_rx: int
    messages_tx: int
    last_reset_at: datetime
    updated_at: datetime


def load(path: Path) -> DriverSession | None:
    """Read the record, or ``None`` when it is absent / corrupt / partial.

    A corrupt or partial file reads as absent; the next ``refresh`` rewrites
    it and (a missing prior, so) stamps a reset.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
        return DriverSession(
            home_id=int(data["home_id"]),
            messages_rx=int(data["messages_rx"]),
            messages_tx=int(data["messages_tx"]),
            last_reset_at=datetime.fromisoformat(data["last_reset_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
    except (ValueError, KeyError, TypeError):
        return None


def refresh(
    path: Path,
    *,
    home_id: int,
    messages_rx: int,
    messages_tx: int,
    now: datetime,
) -> DriverSession:
    """Fold the live counters into the record, stamping a reset when detected.

    A reset is: no prior record, a different ``home_id`` (a different
    controller / a restored backup), or either live counter below the stored
    value (the counters reset to zero on a driver restart). The whole
    read-modify-write is held under an advisory lock so a concurrent monitor
    tick and CLI apply do not lose each other's update.
    """
    with atomic_json.locked(path):
        prior = load(path)
        if (
            prior is None
            or prior.home_id != home_id
            or messages_rx < prior.messages_rx
            or messages_tx < prior.messages_tx
        ):
            last_reset_at = now
        else:
            last_reset_at = prior.last_reset_at
        session = DriverSession(
            home_id=home_id,
            messages_rx=messages_rx,
            messages_tx=messages_tx,
            last_reset_at=last_reset_at,
            updated_at=now,
        )
        atomic_json.write_json(
            path,
            {
                "home_id": session.home_id,
                "messages_rx": session.messages_rx,
                "messages_tx": session.messages_tx,
                "last_reset_at": session.last_reset_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
            },
        )
    return session
