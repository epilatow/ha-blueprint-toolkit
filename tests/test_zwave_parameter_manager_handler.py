#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-asyncio",
#     "pytest-cov",
#     "voluptuous",
#     "PyYAML",
#     "zwave-js-server-python==0.73.0",
#     "pytest-homeassistant-custom-component==0.13.357",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Unit tests for ``zwave_parameter_manager.handler``'s lifecycle code.

Covers the parts that don't require booting Home Assistant: the
``_on_reload`` / ``_on_entity_remove`` / ``_on_entity_rename`` /
``_on_teardown`` mutator callbacks (including the ZPM-specific
driver-reconnect dispatcher unsubscribe), ``_ensure_timer``'s
schedule + re-arm sequencing, the restart-recovery kick shape, the
plan-issue / pending renderers, and the schema-vs-blueprint drift
check. The reconnect signal path + the full reconcile are exercised
in the HACC integration test.

Uses the same lightweight homeassistant-modules stub the other
handler tests install (so ``handler.py``'s HA-side imports resolve)
plus a small mock ``hass``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402
from _handler_stubs import install_homeassistant_stubs  # noqa: E402
from _handler_test_base import (  # noqa: E402
    FrozenNow,
    MockEntry,
    MockHass,
)
from conftest import (  # noqa: E402
    BlueprintDefaultsRoundTripBase,
    BlueprintSchemaDriftBase,
    HandlerArgparseGuardsBase,
)

install_homeassistant_stubs(frozen_now=FrozenNow.value)

from custom_components.blueprint_toolkit.zwave.convergence import (  # noqa: E402, E501
    ConvergenceDevice,
    ConvergenceReport,
    DeviceConvergence,
    ParamConvergence,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager import (  # noqa: E402, E501
    handler,
)
from custom_components.blueprint_toolkit.zwave_parameter_manager.logic import (  # noqa: E402, E501
    Device,
    GenericParamNames,
    ParamId,
    PlanIssue,
    PlannedWrite,
)

# --------------------------------------------------------
# Mock hass surface
# --------------------------------------------------------


def _make_state(
    instance_id: str = "automation.zpm_test",
    *,
    armed_interval_minutes: int = 0,
    cancel_timer: Callable[[], None] | None = None,
    cancel_dispatcher: Callable[[], None] | None = None,
) -> handler.ZpmInstanceState:
    return handler.ZpmInstanceState(
        instance_id=instance_id,
        armed_interval_minutes=armed_interval_minutes,
        cancel_timer=cancel_timer,
        cancel_dispatcher=cancel_dispatcher,
    )


def _hass_with_instances(
    instances: dict[str, handler.ZpmInstanceState],
) -> MockHass:
    h = MockHass()
    entry = MockEntry()
    entry.runtime_data.handlers["zwave_parameter_manager"] = {
        "instances": instances,
        "unsubs": [],
    }
    h.config_entries.entries.append(entry)
    return h


# --------------------------------------------------------
# Mutator callbacks
# --------------------------------------------------------


class TestOnReload:
    def test_cancels_timers_and_dispatchers(self) -> None:
        canceled: list[str] = []
        s1 = _make_state("automation.a", armed_interval_minutes=5)
        s1.cancel_timer = lambda: canceled.append("timer")
        s1.cancel_dispatcher = lambda: canceled.append("dispatcher")
        s2 = _make_state("automation.b", armed_interval_minutes=10)
        h = _hass_with_instances({"automation.a": s1, "automation.b": s2})

        handler._on_reload(h)  # type: ignore[arg-type]

        assert sorted(canceled) == ["dispatcher", "timer"]
        assert s1.cancel_timer is None
        assert s1.cancel_dispatcher is None
        assert s1.armed_interval_minutes == 0
        # State entries themselves remain.
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "zwave_parameter_manager"
        ]
        assert set(bucket["instances"]) == {"automation.a", "automation.b"}


class TestOnEntityRemove:
    def test_drops_state_and_cancels_timer_and_dispatcher(self) -> None:
        canceled: list[str] = []
        s = _make_state("automation.a", armed_interval_minutes=5)
        s.cancel_timer = lambda: canceled.append("timer")
        s.cancel_dispatcher = lambda: canceled.append("dispatcher")
        h = _hass_with_instances(
            {"automation.a": s, "automation.b": _make_state("automation.b")}
        )

        handler._on_entity_remove(h, "automation.a")  # type: ignore[arg-type]

        assert sorted(canceled) == ["dispatcher", "timer"]
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "zwave_parameter_manager"
        ]
        assert set(bucket["instances"]) == {"automation.b"}

    def test_unknown_id_is_noop(self) -> None:
        h = _hass_with_instances({"automation.a": _make_state("automation.a")})
        handler._on_entity_remove(h, "automation.unknown")  # type: ignore[arg-type]


class TestOnEntityRename:
    def test_moves_state_to_new_id(self) -> None:
        s = _make_state("automation.old")
        h = _hass_with_instances({"automation.old": s})

        handler._on_entity_rename(h, "automation.old", "automation.new")

        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "zwave_parameter_manager"
        ]
        assert "automation.old" not in bucket["instances"]
        assert bucket["instances"]["automation.new"] is s
        assert s.instance_id == "automation.new"


class TestOnTeardown:
    def test_cancels_all_timers_and_dispatchers(self) -> None:
        canceled: list[str] = []
        s1 = _make_state("automation.a", armed_interval_minutes=5)
        s1.cancel_timer = lambda: canceled.append("t1")
        s1.cancel_dispatcher = lambda: canceled.append("d1")
        s2 = _make_state("automation.b", armed_interval_minutes=10)
        s2.cancel_timer = lambda: canceled.append("t2")
        h = _hass_with_instances({"automation.a": s1, "automation.b": s2})

        handler._on_teardown(h)  # type: ignore[arg-type]

        assert sorted(canceled) == ["d1", "t1", "t2"]
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "zwave_parameter_manager"
        ]
        assert bucket["instances"] == {}


# --------------------------------------------------------
# Periodic timer arming
# --------------------------------------------------------


class TestEnsureTimer:
    def setup_method(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.unsub_called: list[int] = []

        def _fake_schedule(
            _hass: Any,
            entry: Any,
            *,
            interval: timedelta,
            instance_id: str,
            action: Any,
        ) -> Callable[[], None]:
            handle_index = len(self.calls)
            self.calls.append(
                {
                    "entry": entry,
                    "interval": interval,
                    "instance_id": instance_id,
                    "action": action,
                }
            )

            def _unsub() -> None:
                self.unsub_called.append(handle_index)

            return _unsub

        self._real_schedule = handler.schedule_periodic_with_jitter
        handler.schedule_periodic_with_jitter = _fake_schedule  # type: ignore[assignment]

    def teardown_method(self) -> None:
        handler.schedule_periodic_with_jitter = self._real_schedule

    def test_first_call_arms(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.zpm")
        e = object()

        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]

        assert len(self.calls) == 1
        assert self.calls[0]["entry"] is e
        assert self.calls[0]["interval"] == timedelta(minutes=5)
        assert self.calls[0]["instance_id"] == "automation.zpm"
        assert s.armed_interval_minutes == 5
        assert s.cancel_timer is not None

    def test_same_interval_does_not_re_arm(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.zpm")
        e = object()
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]

        assert len(self.calls) == 1
        assert self.unsub_called == []

    def test_changed_interval_re_arms(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.zpm")
        e = object()
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s, 10)  # type: ignore[arg-type]

        assert self.unsub_called == [0]
        assert len(self.calls) == 2
        assert self.calls[1]["interval"] == timedelta(minutes=10)
        assert s.armed_interval_minutes == 10


# --------------------------------------------------------
# Restart-recovery kick payload
# --------------------------------------------------------


class TestKickWiring:
    def test_spec_kick_variables_are_flat_manual(self) -> None:
        # Flat top-level key; HA's automation.trigger strips a nested
        # ``trigger`` key, so it must not be present.
        assert handler._SPEC.kick_variables == {"trigger_id": "manual"}
        assert "trigger" not in handler._SPEC.kick_variables


# --------------------------------------------------------
# Pure render helpers
# --------------------------------------------------------


class TestRenderHelpers:
    def test_pending_summary_lists_each_entry(self) -> None:
        pending = {
            (5, ParamId(112, 12)): 8,
            (7, ParamId(132, "wakeUpInterval")): 3600,
        }
        out = handler._pending_summary(pending)
        assert "node 5 cc112/12=8" in out
        assert "node 7 cc132/wakeUpInterval=3600" in out

    def _pending_report(
        self,
        *,
        actual: str,
        wake_interval: int,
        last_awake: datetime,
    ) -> ConvergenceReport:
        return ConvergenceReport(
            subsystem="ZPM",
            devices=(
                DeviceConvergence(
                    device=ConvergenceDevice(
                        node_id=7,
                        name="Hall Contact",
                        wake_interval_seconds=wake_interval,
                        last_awake_at=last_awake,
                    ),
                    params=(
                        ParamConvergence(
                            "Wake-up interval",
                            "14400",
                            actual,
                            desired_unit="seconds",
                            actual_unit="seconds",
                        ),
                    ),
                ),
            ),
        )

    def test_pending_signature_ignores_wake_drift(self) -> None:
        # The same pending param under different wake context (a later wake,
        # a different interval) yields the SAME signature -- so a drifting
        # next-wake estimate doesn't re-fire the pending notification.
        a = self._pending_report(
            actual="3600",
            wake_interval=3600,
            last_awake=datetime(2026, 6, 12, 8, 0, tzinfo=UTC),
        )
        b = self._pending_report(
            actual="3600",
            wake_interval=7200,
            last_awake=datetime(2026, 6, 12, 9, 30, tzinfo=UTC),
        )
        assert handler._pending_signature(a) == handler._pending_signature(b)

    def test_pending_signature_changes_with_the_actual_value(self) -> None:
        # A real progress change (the device's live value moved) DOES change
        # the signature, so the notification re-publishes.
        a = self._pending_report(
            actual="3600",
            wake_interval=3600,
            last_awake=datetime(2026, 6, 12, 8, 0, tzinfo=UTC),
        )
        c = self._pending_report(
            actual="7200",
            wake_interval=3600,
            last_awake=datetime(2026, 6, 12, 8, 0, tzinfo=UTC),
        )
        assert handler._pending_signature(a) != handler._pending_signature(c)

    def test_issue_line_escapes_and_formats(self) -> None:
        issue = PlanIssue(
            device=Device(
                node_id=5,
                name="Guest [Bath]",
                manufacturer="Zooz",
                model="ZSE11",
                is_listening=True,
            ),
            concept=GenericParamNames.MOTION_SENSITIVITY,
            reason="no matching parameter",
        )
        line = handler._issue_line(issue)
        assert "motion_sensitivity" in line
        assert "no matching parameter" in line
        # md_escape neutralises the brackets in the device name.
        assert r"Guest \[Bath\]" in line


# --------------------------------------------------------
# Write dispatch
# --------------------------------------------------------


def _dev(*, device_id: str | None) -> Device:
    return Device(
        node_id=5,
        name="n",
        manufacturer="Zooz",
        model="ZSE11",
        is_listening=False,
        device_id=device_id,
    )


class _CapturingHass:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any], bool]] = []

        outer = self

        class _Services:
            async def async_call(
                self,
                domain: str,
                service: str,
                data: dict[str, Any],
                *,
                blocking: bool = False,
            ) -> None:
                outer.calls.append((domain, service, dict(data), blocking))

        self.services = _Services()


class TestDispatchWrites:
    def test_dispatches_both_command_classes(self) -> None:
        import asyncio  # noqa: PLC0415

        dev = _dev(device_id="dev-uuid")
        writes = (
            PlannedWrite(
                device=dev,
                concept=GenericParamNames.MOTION_SENSITIVITY,
                policy="p",
                id=ParamId(112, 12),
                value=8,
                generic_value=8,
            ),
            PlannedWrite(
                device=dev,
                concept=GenericParamNames.WAKE_UP_INTERVAL,
                policy="p",
                id=ParamId(132, "wakeUpInterval"),
                value=3600,
                generic_value=3600,
            ),
        )
        h = _CapturingHass()
        asyncio.run(handler._dispatch_writes(h, writes))  # type: ignore[arg-type]

        assert (
            "zwave_js",
            "set_config_parameter",
            {
                "device_id": "dev-uuid",
                "endpoint": 0,
                "parameter": 12,
                "value": 8,
            },
            False,
        ) in h.calls
        assert (
            "zwave_js",
            "set_value",
            {
                "device_id": "dev-uuid",
                "command_class": 132,
                "endpoint": 0,
                "property": "wakeUpInterval",
                "value": 3600,
            },
            False,
        ) in h.calls

    def test_partial_config_param_uses_set_value(self) -> None:
        # A bitmask / partial Configuration param carries a property_key; it
        # must go through set_value so the key is not dropped.
        import asyncio  # noqa: PLC0415

        writes = (
            PlannedWrite(
                device=_dev(device_id="dev-uuid"),
                concept=GenericParamNames.LIGHT_ON_MOTION,
                policy="p",
                id=ParamId(112, 12, 255),
                value=1,
                generic_value=True,
            ),
        )
        h = _CapturingHass()
        asyncio.run(handler._dispatch_writes(h, writes))  # type: ignore[arg-type]
        assert h.calls == [
            (
                "zwave_js",
                "set_value",
                {
                    "device_id": "dev-uuid",
                    "command_class": 112,
                    "endpoint": 0,
                    "property": 12,
                    "property_key": 255,
                    "value": 1,
                },
                False,
            )
        ]

    def test_skips_write_without_device_id(self) -> None:
        import asyncio  # noqa: PLC0415

        writes = (
            PlannedWrite(
                device=_dev(device_id=None),
                concept=GenericParamNames.MOTION_SENSITIVITY,
                policy="p",
                id=ParamId(112, 12),
                value=8,
                generic_value=8,
            ),
        )
        h = _CapturingHass()
        asyncio.run(handler._dispatch_writes(h, writes))  # type: ignore[arg-type]
        assert h.calls == []


# --------------------------------------------------------
# Schema-vs-blueprint drift + defaults + argparse guards
# --------------------------------------------------------


class TestBlueprintSchemaDrift(BlueprintSchemaDriftBase):
    handler = handler
    blueprint_filename = "zwave_parameter_manager.yaml"


class TestBlueprintDefaultsRoundTrip(BlueprintDefaultsRoundTripBase):
    handler = handler
    blueprint_filename = "zwave_parameter_manager.yaml"
    template_defaults = {
        "instance_id": "automation.zpm_default_check",
        "trigger_id": "manual",
    }


class TestArgparseGuards(HandlerArgparseGuardsBase):
    handler = handler


if __name__ == "__main__":
    sys.exit(
        pytest.main([__file__, "-v", "-p", "no:homeassistant", *sys.argv[1:]])
    )
