# This is AI generated code
"""Render a ConvergenceReport as a persistent-notification body.

The automation surface for the shared desired / actual / pending model.
Each device renders as a clickable device link (its name plus the HA
device page) annotated with location, node id, wake interval, and
expected next wake, then the params being set -- each as
``actual -> desired``. The desired report lists every device and param;
the pending report lists only the devices and params not yet converged.
The unused report renders ``Plan.unused`` -- configured policies /
settings that landed on no device -- as a flat bullet list, off the same
planner output a future CLI view will render as rows.

Pure markdown assembly: the handler wraps the returned body in a
``PersistentNotification`` spec (instance id, title, attribution) and
decides when to fire it. Convergence and the humanised values come from
the shared model and ``zwave.formatting``, so the CLI table renderer
reads the same derivations rather than recomputing them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..helpers_logic import device_link, md_escape
from ..zwave.convergence import (
    ConvergenceReport,
    DeviceConvergence,
    ParamConvergence,
)
from ..zwave.formatting import format_wake_time, humanize_duration

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .logic import UnusedSetting


def render_report_body(report: ConvergenceReport, *, pending_only: bool) -> str:
    """Markdown body for a desired (``pending_only=False``) or pending
    (``True``) report.

    Returns ``""`` when a pending report has nothing pending, so the
    caller dismisses the notification instead of posting an empty one.
    """

    devices = report.pending_devices if pending_only else report.devices
    if not devices:
        return ""
    return "\n\n".join(
        _device_block(d, pending_only=pending_only) for d in devices
    )


def _device_block(dc: DeviceConvergence, *, pending_only: bool) -> str:
    device = dc.device
    if device.device_id is not None:
        head = device_link(device.name, device.device_id)
    else:
        head = md_escape(device.name)
    notes: list[str] = []
    if device.location:
        notes.append(md_escape(device.location))
    notes.append(f"node {device.node_id}")
    if device.wake_interval_seconds is not None:
        notes.append(
            f"wakes every {humanize_duration(device.wake_interval_seconds)}"
        )
    next_wake = device.expected_next_wake
    if next_wake is not None:
        notes.append(f"next wake ~{format_wake_time(next_wake)}")
    header = f"{head} -- {', '.join(notes)}"
    params = dc.pending_params if pending_only else dc.params
    if not params:
        return header
    body = "\n".join(_param_line(p) for p in params)
    return f"{header}\n\n{body}"


def _with_unit(value: str, unit: str) -> str:
    """Compose a value and its unit into a display string
    (``"3600" + "seconds" -> "3600 seconds"``; no unit -> the value as-is)."""

    return f"{value} {unit}" if unit else value


def _param_line(param: ParamConvergence) -> str:
    """``- concept: <desired> <unit> (dev: <current> -> <pending>)`` as normal
    text: the generic policy value (with its concept unit) up front, then the
    device's live and target values in the parenthetical -- the same
    generic/device split the CLI table shows."""

    label = param.concept or param.param
    desired = md_escape(_with_unit(param.concept_desired, param.concept_unit))
    current = "unread" if param.actual is None else md_escape(param.actual)
    pending = md_escape(param.desired)
    return f"- {md_escape(label)}: {desired} (dev: {current} -> {pending})"


def render_unused_body(unused: Sequence[UnusedSetting]) -> str:
    """Markdown body for the unused-config report.

    One bullet per finding -- a policy whose selector matched nothing, or
    a setting no matched device exposed. Returns ``""`` when nothing is
    unused so the handler dismisses the notification instead of posting
    an empty one.
    """

    if not unused:
        return ""
    return "\n".join(_unused_line(u) for u in unused)


def _unused_line(u: UnusedSetting) -> str:
    if u.concept is None:
        return f"- policy `{u.policy}`: {u.reason}"
    return f"- policy `{u.policy}` setting `{u.concept}`: {u.reason}"
