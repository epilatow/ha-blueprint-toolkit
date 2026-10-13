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
``actual`` the live value at the same ``ParamId``, both split into a
unitless display value plus the device unit by ``_split_value`` so the
string compare ``ParamConvergence.converged`` holds (equal raw ints render
to equal value+unit; an unread value renders to ``None`` and so never
converges). The row also carries the generic concept name, the value the
policy set, and the concept's own unit, so a renderer can show either view.

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
from .catalog import CATALOG

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
    desired_value, desired_unit = _split_value(meta, write.value)
    if actual is None:
        actual_value, actual_unit = None, ""
    else:
        actual_value, actual_unit = _split_value(meta, actual)
    return ParamConvergence(
        param=label,
        desired=desired_value,
        actual=actual_value,
        desired_unit=desired_unit,
        actual_unit=actual_unit,
        concept=str(write.concept),
        concept_desired=_render_generic(write.generic_value),
        concept_unit=CATALOG[write.concept].units or "",
    )


def _render_generic(value: bool | float) -> str:
    """The generic concept value (what the policy set) as a display string.

    ``bool`` is checked first -- it is an ``int`` subclass -- so a boolean
    concept renders ``true`` / ``false`` rather than ``1`` / ``0``.
    """

    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _split_value(meta: ParamMeta | None, value: int) -> tuple[str, str]:
    """A raw device value as a ``(display, unit)`` pair.

    Desired and actual both split here, so equal raw values produce equal
    pairs and the report's value-plus-unit convergence holds. An option value
    shows its label plus the raw int and carries no unit (the label is the
    whole meaning); a unit-bearing value is the bare int plus its unit;
    everything else is the bare int with no unit. A renderer composes
    ``display unit`` to get the canonical string, or shows them separately.
    """

    if meta is not None:
        if value in meta.states:
            return f"{meta.states[value]} ({value})", ""
        if meta.unit:
            return str(value), meta.unit
    return str(value), ""
