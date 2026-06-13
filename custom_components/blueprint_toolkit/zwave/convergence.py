# This is AI generated code
"""Shared Z-Wave convergence model (pure logic, no HA / socket deps).

The desired / actual / pending model shared by the Z-Wave Parameter
Manager and Route Manager. Each subsystem normalises its devices to
``DeviceConvergence`` rows; the report renderers (a table for the CLI,
a persistent notification for the automation) consume the shared
``ConvergenceReport``. The renderers are not here -- they land with
their consumers; this commit locks the model + the convergence
derivations only.

A param is *converged* when ``actual == desired`` and *pending*
otherwise, for any reason (never applied, or reset / changed
out-of-band). The reconcile re-issues to converge regardless, so there
is no separate "drift" state.

Each subsystem renders its desired / actual to canonical display
strings, so this layer compares + carries them without knowing
route-vs-int semantics. ``wake_interval_seconds`` + ``last_awake_at``
(the last scheduled wake, from the node-status history -- NOT the live
snapshot's last-seen, which also moves on unsolicited sensor reports)
drive an approximate ``expected_next_wake``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ConvergenceDevice:
    """Identity + wake context for a device in a convergence report.

    ``device_id`` is the HA device-registry UUID, present on the HA path
    (the automation renders it as a clickable device link) and ``None``
    on the CLI path. ``location`` is the device's room / area label.
    ``last_awake_at`` is the last scheduled wake; ``None`` for
    always-listening devices or when the last wake is unknown (e.g. the
    wake interval exceeds recorder retention).
    """

    node_id: int
    name: str
    device_id: str | None = None
    location: str | None = None
    wake_interval_seconds: int | None = None
    last_awake_at: datetime | None = None

    @property
    def expected_next_wake(self) -> datetime | None:
        """Estimated next scheduled wake, or ``None`` if not derivable.

        ``last_awake_at`` plus the wake interval. An estimate: the
        device's own clock drifts and zwave-js publishes no exact ETA.
        ``None`` when there is no wake interval (always-listening) or no
        known last wake.
        """

        if self.wake_interval_seconds is None or self.last_awake_at is None:
            return None
        return self.last_awake_at + timedelta(
            seconds=self.wake_interval_seconds
        )


@dataclass(frozen=True)
class ParamConvergence:
    """One (param, desired, actual) row for a device.

    The device view is split value-from-unit: ``desired`` / ``actual`` are the
    device value display strings WITHOUT the unit (an option value keeps its
    ``Label (n)`` form; ``actual`` is ``None`` when the live value is unread),
    and ``desired_unit`` / ``actual_unit`` carry the device unit (``""`` for an
    option / unitless value). A renderer either composes ``value unit`` (the
    notification) or shows the value and unit in separate columns (the CLI).

    ``concept`` / ``concept_desired`` / ``concept_unit`` are the optional
    generic view (the higher-level concept name, the value the config set, and
    the concept's own unit, in ZPM); empty when there is no generic layer (ZRM
    routes). Convergence is computed on the device view (value plus unit).
    """

    param: str
    desired: str
    actual: str | None = None
    desired_unit: str = ""
    actual_unit: str = ""
    concept: str = ""
    concept_desired: str = ""
    concept_unit: str = ""

    @property
    def converged(self) -> bool:
        return (
            self.actual == self.desired
            and self.actual_unit == self.desired_unit
        )


@dataclass(frozen=True)
class DeviceConvergence:
    """A device plus its per-param convergence rows."""

    device: ConvergenceDevice
    params: tuple[ParamConvergence, ...] = ()

    @property
    def converged(self) -> bool:
        """True when every param is converged (vacuously, if none)."""

        return all(p.converged for p in self.params)

    @property
    def pending_params(self) -> tuple[ParamConvergence, ...]:
        return tuple(p for p in self.params if not p.converged)


@dataclass(frozen=True)
class ConvergenceReport:
    """A subsystem's full desired-vs-actual state across devices.

    The desired report renders every device; the pending report renders
    only ``pending_devices`` (those with at least one pending param).
    """

    subsystem: str
    devices: tuple[DeviceConvergence, ...] = ()

    @property
    def converged(self) -> bool:
        return all(d.converged for d in self.devices)

    @property
    def pending_devices(self) -> tuple[DeviceConvergence, ...]:
        return tuple(d for d in self.devices if not d.converged)

    @property
    def converged_count(self) -> int:
        return sum(1 for d in self.devices for p in d.params if p.converged)

    @property
    def pending_count(self) -> int:
        return sum(1 for d in self.devices for p in d.params if not p.converged)
