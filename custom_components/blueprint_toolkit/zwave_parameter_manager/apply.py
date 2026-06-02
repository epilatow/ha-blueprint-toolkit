# This is AI generated code
"""Decide which planned writes to issue this reconcile cycle.

The pure core of the apply path. The handler dispatches the actual
``zwave_js`` service calls and owns the pending map's lifetime; this
module only decides *which* writes to issue now, given the desired plan,
the live values, and what is already pending.

Each command is issued to the driver at most once per pending epoch: a
mismatched write is suppressed while the pending map already records its
value. We do not rely on the add-on de-duplicating its wake-up queue (an
unverifiable implementation detail), and we never pile up duplicates
within an epoch. The handler ends an epoch -- and so allows a re-issue --
by clearing the pending map whenever the queue may have flushed: on a
driver reconnect (an add-on restart), and implicitly on an HA Core restart
(the map is in-memory, so it starts empty and the first reconcile re-issues
every mismatched write -- the conservative recovery for a flush we could
not observe while Core was down).

A converged write (actual == desired) clears its pending entry, so a later
out-of-band divergence is a fresh command and re-issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TypeAlias

    from .logic import ParamId, Plan, PlannedWrite

    # A pending write's key: the node it targets and the parameter on it.
    PendingKey: TypeAlias = tuple[int, ParamId]


@dataclass(frozen=True)
class ApplyDecision:
    """The outcome of one reconcile decision.

    ``writes`` is the subset of the plan to dispatch now; ``pending`` maps
    each still-unconverged write's key to the value last issued for it, kept
    (in memory) for the next cycle. Converged or no-longer-planned writes
    are dropped.
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
    the handler clears ``pending`` on a queue flush so the next cycle
    re-issues. The returned ``pending`` carries forward every still-
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
