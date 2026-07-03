# This is AI generated code
"""Shared ZPM pending-write store (``zpm_pending.json``).

The set of parameter writes ZPM has issued to the mesh but not yet seen
converge. Both the in-process handler and the standalone ``zwavectl apply``
read + update it so neither re-issues a command the other already queued.

A single ``issued_at`` stamps the current pending epoch: a Z-Wave JS driver
restart flushes the WHOLE wake-up queue at once, so if the driver restarted
after ``issued_at`` (``issued_at < last_reset_at`` from the shared
``zwave.driver_session`` record) every listed command was flushed and the set
is stale. ``home_id`` scopes the file to the controller, so a restored backup
on a different network can't be mistaken for the same queue.

Writes MERGE rather than replace: an actor updates only the keys its own plan
covers and preserves the rest, so a second ZPM instance (or the CLI) driving a
different policy doesn't clobber this one's pending. Pure file I/O -- no HA
imports -- so the CLI venv imports it too.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ..zwave import atomic_json
from .logic import ParamId

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from typing import TypeAlias

    # A pending write's key: the node it targets and the parameter on it.
    PendingKey: TypeAlias = tuple[int, ParamId]

# Location of the pending store, relative to the HA config dir. The CLI's
# default resolves to the same absolute path under /config.
PENDING_REL_PATH = "blueprint_toolkit/zpm_pending.json"


@dataclass(frozen=True)
class PendingCommand:
    """One issued-but-unconverged write, as persisted."""

    node_id: int
    command_class: int
    property_: int | str
    property_key: int | None
    value: int

    def key(self) -> tuple[int, ParamId]:
        return (
            self.node_id,
            ParamId(self.command_class, self.property_, self.property_key),
        )


@dataclass(frozen=True)
class PendingState:
    home_id: int
    issued_at: datetime
    commands: tuple[PendingCommand, ...]


def load(path: Path) -> PendingState | None:
    """Read the store, or ``None`` when absent / corrupt / partial."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
        commands = tuple(
            PendingCommand(
                node_id=int(c["node_id"]),
                command_class=int(c["command_class"]),
                property_=c["property"],
                property_key=c["property_key"],
                value=int(c["value"]),
            )
            for c in data["commands"]
        )
        return PendingState(
            home_id=int(data["home_id"]),
            issued_at=datetime.fromisoformat(data["issued_at"]),
            commands=commands,
        )
    except (ValueError, KeyError, TypeError):
        return None


def read_valid(
    path: Path, *, home_id: int, last_reset_at: datetime
) -> dict[PendingKey, int]:
    """The still-queued pending map, or empty when stale / absent / foreign.

    Empty when the file is missing, records a different ``home_id``, or was
    issued before the last driver reset (the whole queue was flushed).
    """
    state = load(path)
    if (
        state is None
        or state.home_id != home_id
        or state.issued_at < last_reset_at
    ):
        return {}
    return {c.key(): c.value for c in state.commands}


def merge(
    path: Path,
    *,
    home_id: int,
    last_reset_at: datetime,
    plan_keys: frozenset[PendingKey],
    decision_pending: Mapping[PendingKey, int],
    now: datetime,
) -> None:
    """Fold this actor's decision into the store under a lock.

    Keys the caller's plan covers (``plan_keys``) are replaced by
    ``decision_pending`` (converged / removed writes drop out); keys outside
    the plan -- another instance's or the CLI's pending -- are preserved.
    ``issued_at`` (the epoch start) is kept while the prior epoch is still
    valid and reset to ``now`` only when the prior store was stale / absent.
    """
    with atomic_json.locked(path):
        prior = load(path)
        if (
            prior is not None
            and prior.home_id == home_id
            and prior.issued_at >= last_reset_at
        ):
            old = {c.key(): c.value for c in prior.commands}
            issued_at = prior.issued_at
        else:
            old = {}
            issued_at = now
        merged: dict[PendingKey, int] = {
            key: value for key, value in old.items() if key not in plan_keys
        }
        merged.update(decision_pending)
        if not merged:
            path.unlink(missing_ok=True)
            return
        commands = [
            PendingCommand(
                node_id,
                pid.command_class,
                pid.property_,
                pid.property_key,
                value,
            )
            for (node_id, pid), value in merged.items()
        ]
        commands.sort(
            key=lambda c: (
                c.node_id,
                c.command_class,
                str(c.property_),
                str(c.property_key),
            )
        )
        atomic_json.write_json(
            path,
            {
                "home_id": home_id,
                "issued_at": issued_at.isoformat(),
                "commands": [
                    {
                        "node_id": c.node_id,
                        "command_class": c.command_class,
                        "property": c.property_,
                        "property_key": c.property_key,
                        "value": c.value,
                    }
                    for c in commands
                ],
            },
        )
