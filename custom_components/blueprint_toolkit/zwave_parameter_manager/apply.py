# This is AI generated code
"""Decide which planned writes to issue this reconcile cycle.

The pure core of the apply path. The caller (the handler or the CLI's
``apply``) dispatches the actual ``zwave_js`` service calls and persists the
pending map to the shared store (``pending_store``); this module only decides
*which* writes to issue now, given the desired plan, the live values, and what
is already pending.

Each command is issued to the driver at most once per pending epoch: a
mismatched write is suppressed while the pending map already records its
value. We do not rely on the add-on de-duplicating its wake-up queue (an
unverifiable implementation detail), and we never pile up duplicates within an
epoch. An epoch ends -- and a re-issue is allowed -- when the driver's wake-up
queue is flushed by a restart; the caller detects that from the driver-session
record and passes an EMPTY ``pending`` map for the flushed epoch (see
``pending_store.read_valid`` keyed off ``last_reset_at``), so the next cycle
re-issues every mismatched write.

A converged write (actual == desired) drops out of the returned ``pending``,
so a later out-of-band divergence is a fresh command and re-issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .logic import ParamId, Plan, PlannedWrite

    # A pending write's key: the node it targets and the parameter on it.
    type PendingKey = tuple[int, ParamId]


@dataclass(frozen=True)
class ApplyDecision:
    """The outcome of one reconcile decision.

    ``writes`` is the subset of the plan to dispatch now; ``pending`` maps
    each still-unconverged write's key to the value last issued for it, which
    the caller persists to the shared pending store for the next cycle.
    Converged or no-longer-planned writes are dropped.
    """

    writes: tuple[PlannedWrite, ...]
    pending: dict[PendingKey, int]


def select_writes(
    plan: Plan,
    actuals: Mapping[int, Mapping[ParamId, int | None]],
    pending: Mapping[PendingKey, int],
) -> ApplyDecision:
    """Decide which of ``plan``'s writes to issue this cycle.

    ``actuals`` is keyed by ``node_id``; ``pending`` maps a write's key to
    the value last issued for it. A mismatched write is issued unless the
    pending map already records the same value (already queued this epoch);
    the caller passes an empty ``pending`` for a flushed epoch so the next
    cycle re-issues. The returned ``pending`` carries forward every still-
    unconverged write, so a converged or removed write clears itself.
    """

    to_issue: list[PlannedWrite] = []
    new_pending: dict[PendingKey, int] = {}
    for write in plan.writes:
        node_id = write.device.node_id
        if actuals.get(node_id, {}).get(write.id) == write.value:
            continue
        key = (node_id, write.id)
        if pending.get(key) != write.value:
            to_issue.append(write)
        new_pending[key] = write.value
    return ApplyDecision(writes=tuple(to_issue), pending=new_pending)
