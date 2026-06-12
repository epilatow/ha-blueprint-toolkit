# This is AI generated code
"""Join a ZPM Plan against live values into a ConvergenceReport.

The pure step between planning and the report renderers. ``build_report``
takes the planned writes (``evaluate_policies``'s output), the per-node
wake context (``ConvergenceDevice``), and the per-node live values, and
produces the shared ``ConvergenceReport`` the persistent-notification
renderer and the CLI table both consume.

Only devices ZPM actually plans a write for appear -- an unmanaged fleet
node has no desired state to converge against. Each planned write becomes
one ``ParamConvergence`` row: ``desired`` is the write's raw value, the
``actual`` the live value at the same ``ParamId``, both rendered through
``_render_value`` so the string compare ``ParamConvergence.converged``
performs holds (equal raw ints render to equal strings; an unread value
renders to ``None`` and so never converges).

Plan warnings / errors are not part of the convergence model; the
handler surfaces those on its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..zwave.convergence import (
    ConvergenceDevice,
    ConvergenceReport,
    DeviceConvergence,
    ParamConvergence,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .logic import ParamId, ParamMeta, Plan, PlannedWrite

_SUBSYSTEM = "Z-Wave Parameter Manager"


def build_report(
    plan: Plan,
    convergence: Mapping[int, ConvergenceDevice],
    actuals: Mapping[int, Mapping[ParamId, int | None]],
    *,
    subsystem: str = _SUBSYSTEM,
) -> ConvergenceReport:
    """The desired-vs-actual report for ``plan``.

    ``convergence`` and ``actuals`` are keyed by ``node_id``. A node with
    a planned write but no ``convergence`` entry falls back to a bare
    ``ConvergenceDevice`` off the write's own ``Device``; a missing
    ``actuals`` entry reads as all-unread. Devices appear in first-write
    order; each device's params in planned-write order.
    """

    by_node: dict[int, list[PlannedWrite]] = {}
    for write in plan.writes:
        by_node.setdefault(write.device.node_id, []).append(write)

    devices: list[DeviceConvergence] = []
    for node_id, writes in by_node.items():
        device = convergence.get(node_id) or _bare_device(writes[0])
        live = actuals.get(node_id, {})
        params = tuple(
            _param_row(write, live.get(write.id)) for write in writes
        )
        devices.append(DeviceConvergence(device=device, params=params))
    return ConvergenceReport(subsystem=subsystem, devices=tuple(devices))


def _bare_device(write: PlannedWrite) -> ConvergenceDevice:
    """Wake-context-free device for a planned node absent from the
    convergence map (gone between read and plan)."""

    return ConvergenceDevice(
        node_id=write.device.node_id, name=write.device.name
    )


def _param_row(write: PlannedWrite, actual: int | None) -> ParamConvergence:
    meta = next((pm for pm in write.device.params if pm.id == write.id), None)
    label = (
        meta.label if meta is not None and meta.label else str(write.concept)
    )
    return ParamConvergence(
        param=label,
        desired=_render_value(meta, write.value),
        actual=None if actual is None else _render_value(meta, actual),
        concept=str(write.concept),
        concept_desired=_render_generic(write.generic_value),
    )


def _render_generic(value: bool | int | float) -> str:
    """The generic concept value (what the policy set) as a display string.

    ``bool`` is checked first -- it is an ``int`` subclass -- so a boolean
    concept renders ``true`` / ``false`` rather than ``1`` / ``0``.
    """

    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_value(meta: ParamMeta | None, value: int) -> str:
    """A raw device value as a canonical display string.

    Desired and actual both render here, so equal raw values produce equal
    strings and the report's string-compare convergence holds. An option
    value shows its label plus the raw int; a unit-bearing value shows the
    unit; everything else is the bare int.
    """

    if meta is not None:
        if value in meta.states:
            return f"{meta.states[value]} ({value})"
        if meta.unit:
            return f"{value} {meta.unit}"
    return str(value)
