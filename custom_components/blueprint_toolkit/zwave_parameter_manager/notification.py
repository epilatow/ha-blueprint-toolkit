# This is AI generated code
"""Render a ConvergenceReport as a persistent-notification body.

The automation surface for the shared desired / actual / pending model.
Each device renders as a clickable device link (its name plus the HA
device page) annotated with location, node id, wake interval, and
expected next wake, then the params being set -- each as
``actual -> desired``. The desired report lists every device and param;
the pending report lists only the devices and params not yet converged.

Pure markdown assembly: the handler wraps the returned body in a
``PersistentNotification`` spec (instance id, title, attribution) and
decides when to fire it. Convergence and the humanised values come from
the shared model and ``zwave.formatting``, so the CLI table renderer
reads the same derivations rather than recomputing them.
"""

from __future__ import annotations

from ..helpers_logic import device_link, md_escape
from ..zwave.convergence import (
    ConvergenceReport,
    DeviceConvergence,
    ParamConvergence,
)
from ..zwave.formatting import format_wake_time, humanize_duration


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


def _param_line(param: ParamConvergence) -> str:
    actual = f"`{param.actual}`" if param.actual is not None else "unread"
    return f"- `{param.param}`: {actual} -> `{param.desired}`"
