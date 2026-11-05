#!/usr/bin/env -S uv run --script --exact
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-asyncio",
#     "pytest-cov",
#     "probatio",
#     "PyYAML",
#     "pytest-homeassistant==2026.11.0",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Unit tests for ``battery_watchdog.handler``.

Covers the parts that don't require booting HA: mutator
callbacks, ``_ensure_timer`` re-arm sequencing, the
restart-recovery kick payload, argparse (regex helper
delegation, the include_entities exclusivity rule, schema
range checks), and the blueprint <-> schema drift checks.
The service layer's scan runs end to end in
``test_battery_watchdog_integration.py``.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar

REPO_ROOT = Path(__file__).parent.parent
_SCRIPT_PATH = (
    REPO_ROOT
    / "custom_components"
    / "blueprint_toolkit"
    / "battery_watchdog"
    / "handler.py"
)
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402
from _handler_stubs import install_homeassistant_stubs  # noqa: E402
from _handler_test_base import (  # noqa: E402
    ArgparseCapture,
    FakeServiceCall,
    FrozenNow,
    MockEntry,
    MockHass,
)
from conftest import (  # noqa: E402
    BlueprintDefaultsRoundTripBase,
    BlueprintSchemaDriftBase,
    HandlerArgparseGuardsBase,
)

_stubs = install_homeassistant_stubs(frozen_now=FrozenNow.value)

from custom_components.blueprint_toolkit.battery_watchdog import (  # noqa: E402
    handler,
)


def _make_state(
    instance_id: str = "automation.bw_test",
    *,
    armed_interval_minutes: int = 0,
    cancel_timer: Callable[[], None] | None = None,
) -> handler.BwInstanceState:
    return handler.BwInstanceState(
        instance_id=instance_id,
        armed_interval_minutes=armed_interval_minutes,
        cancel_timer=cancel_timer,
    )


def _hass_with_instances(
    instances: dict[str, handler.BwInstanceState],
) -> MockHass:
    h = MockHass()
    entry = MockEntry()
    entry.runtime_data.handlers["battery_watchdog"] = {
        "instances": instances,
        "unsubs": [],
    }
    h.config_entries.entries.append(entry)
    return h


def _bucket(h: MockHass) -> dict[str, Any]:
    handlers: dict[str, dict[str, Any]] = h.config_entries.entries[
        0
    ].runtime_data.handlers
    return handlers["battery_watchdog"]


# --------------------------------------------------------
# Mutator callbacks
# --------------------------------------------------------


class TestOnReload:
    def test_cancels_pending_timers(self) -> None:
        canceled: list[int] = []
        s1 = _make_state(
            "automation.a",
            armed_interval_minutes=5,
            cancel_timer=lambda: canceled.append(1),
        )
        s2 = _make_state("automation.b", armed_interval_minutes=10)
        h = _hass_with_instances({"automation.a": s1, "automation.b": s2})

        handler._on_reload(h)

        assert canceled == [1]
        assert s1.cancel_timer is None
        assert s1.armed_interval_minutes == 0
        assert set(_bucket(h)["instances"]) == {"automation.a", "automation.b"}


class TestOnEntityRemove:
    def test_drops_state_and_cancels_timer(self) -> None:
        canceled: list[int] = []
        s = _make_state(
            "automation.a",
            armed_interval_minutes=5,
            cancel_timer=lambda: canceled.append(1),
        )
        h = _hass_with_instances(
            {"automation.a": s, "automation.b": _make_state("automation.b")}
        )

        handler._on_entity_remove(h, "automation.a")

        assert canceled == [1]
        assert set(_bucket(h)["instances"]) == {"automation.b"}


class TestOnEntityRename:
    def test_moves_state_to_new_id(self) -> None:
        s = _make_state("automation.old")
        h = _hass_with_instances({"automation.old": s})

        handler._on_entity_rename(h, "automation.old", "automation.new")

        assert "automation.old" not in _bucket(h)["instances"]
        assert _bucket(h)["instances"]["automation.new"] is s
        assert s.instance_id == "automation.new"


class TestOnTeardown:
    def test_cancels_all_and_clears(self) -> None:
        canceled: list[int] = []
        s1 = _make_state(
            "automation.a", cancel_timer=lambda: canceled.append(1)
        )
        s2 = _make_state(
            "automation.b", cancel_timer=lambda: canceled.append(2)
        )
        h = _hass_with_instances({"automation.a": s1, "automation.b": s2})

        handler._on_teardown(h)

        assert sorted(canceled) == [1, 2]
        assert _bucket(h)["instances"] == {}


# --------------------------------------------------------
# _ensure_timer
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
        s = _make_state("automation.bw")
        e = object()

        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]

        assert len(self.calls) == 1
        assert self.calls[0]["entry"] is e
        assert self.calls[0]["interval"] == timedelta(minutes=5)
        assert self.calls[0]["instance_id"] == "automation.bw"
        assert s.armed_interval_minutes == 5

    def test_same_interval_does_not_re_arm(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.bw")
        e = object()
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]

        assert len(self.calls) == 1
        assert self.unsub_called == []

    def test_changed_interval_re_arms(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.bw")
        e = object()
        handler._ensure_timer(h, e, s, 5)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s, 10)  # type: ignore[arg-type]

        assert self.unsub_called == [0]
        assert self.calls[1]["interval"] == timedelta(minutes=10)
        assert s.armed_interval_minutes == 10


# --------------------------------------------------------
# Argparse
# --------------------------------------------------------


def _valid_argparse_payload(**overrides: Any) -> dict[str, Any]:
    """Return a schema-valid raw payload with optional overrides."""
    payload: dict[str, Any] = {
        "instance_id": "automation.bw_test",
        "trigger_id": "manual",
        "battery_warning_level_raw": 25,
        "include_integrations_raw": [],
        "exclude_integrations_raw": [],
        "exclude_device_name_regex_raw": "",
        "include_entities_raw": [],
        "exclude_entities_raw": [],
        "exclude_entity_id_regex_raw": "",
        "exclude_entity_name_regex_raw": "",
        "check_interval_minutes_raw": 5,
        "validate_includes_excludes_raw": True,
        "debug_logging_raw": False,
    }
    payload.update(overrides)
    return payload


class _ArgparseHarness:
    """Swap the service layer and config-error emitter for captures."""

    def setup_method(self) -> None:
        self.capture = ArgparseCapture()
        self._real_service_layer = handler._async_service_layer
        handler._async_service_layer = self.capture  # type: ignore[assignment]
        self.config_errors: list[list[str]] = []

        async def _capture_errors(
            _hass: Any,
            _instance_id: str,
            errors: list[str],
        ) -> None:
            self.config_errors.append(errors)

        self._real_emit = handler._emit_config_error
        handler._emit_config_error = _capture_errors

    def teardown_method(self) -> None:
        handler._async_service_layer = self._real_service_layer
        handler._emit_config_error = self._real_emit

    def run(self, **overrides: Any) -> None:
        call = FakeServiceCall(_valid_argparse_payload(**overrides))
        asyncio.run(
            handler._async_argparse(MockHass(), call, now=FrozenNow.value)  # type: ignore[arg-type]
        )


class TestArgparsePassThrough(_ArgparseHarness):
    def test_valid_payload_reaches_the_service_layer(self) -> None:
        self.run(
            battery_warning_level_raw=45,
            exclude_entities_raw=["sensor.phone_battery"],
        )

        assert self.config_errors == [[]]
        (kw,) = self.capture.calls
        assert kw["warning_level"] == 45
        assert kw["exclude_entities"] == ["sensor.phone_battery"]
        assert kw["include_entities"] == []

    def test_regex_fields_join_with_pipe(self) -> None:
        self.run(
            exclude_device_name_regex_raw="^Phone\nTablet$",
            exclude_entity_id_regex_raw="sensor\\.a\nsensor\\.b",
            exclude_entity_name_regex_raw="Spare\nTest",
        )

        assert self.config_errors == [[]]
        (kw,) = self.capture.calls
        assert kw["exclude_device_name_regex"] == "^Phone|Tablet$"
        assert kw["exclude_entity_id_regex"] == "sensor\\.a|sensor\\.b"
        assert kw["exclude_entity_name_regex"] == "Spare|Test"

    def test_bad_regex_emits_config_error(self) -> None:
        self.run(exclude_entity_name_regex_raw="ok\n[invalid")

        assert self.capture.calls == []
        assert len(self.config_errors) == 1
        assert "exclude_entity_name_regex" in "\n".join(self.config_errors[0])


class TestArgparseIncludeEntities(_ArgparseHarness):
    def test_include_entities_alone_is_valid(self) -> None:
        self.run(include_entities_raw=["sensor.door_battery"])

        assert self.config_errors == [[]]
        (kw,) = self.capture.calls
        assert kw["include_entities"] == ["sensor.door_battery"]

    def test_include_entities_with_other_filters_is_an_error(self) -> None:
        self.run(
            include_entities_raw=["sensor.door_battery"],
            exclude_integrations_raw=["hue"],
            exclude_entity_name_regex_raw="Spare",
        )

        assert self.capture.calls == []
        (errors,) = self.config_errors
        joined = "\n".join(errors)
        assert "include_entities" in joined
        assert "exclude_integrations" in joined
        assert "exclude_entity_name_regex" in joined
        assert "include_integrations" not in joined

    def test_warning_level_and_interval_are_not_filters(self) -> None:
        self.run(
            include_entities_raw=["sensor.door_battery"],
            battery_warning_level_raw=50,
            check_interval_minutes_raw=60,
            validate_includes_excludes_raw=False,
            debug_logging_raw=True,
        )

        assert self.config_errors == [[]]
        assert len(self.capture.calls) == 1


class TestArgparseRanges(_ArgparseHarness):
    @pytest.mark.parametrize("level", [-1, 101])
    def test_out_of_range_warning_level_rejected(self, level: int) -> None:
        self.run(battery_warning_level_raw=level)

        assert self.capture.calls == []
        assert "battery_warning_level_raw" in "\n".join(self.config_errors[0])

    @pytest.mark.parametrize("level", [0, 100])
    def test_warning_level_bounds_accepted(self, level: int) -> None:
        self.run(battery_warning_level_raw=level)

        assert self.config_errors == [[]]

    def test_zero_check_interval_rejected(self) -> None:
        self.run(check_interval_minutes_raw=0)

        assert self.capture.calls == []
        assert "check_interval_minutes_raw" in "\n".join(self.config_errors[0])


# --------------------------------------------------------
# Restart-recovery kick payload
# --------------------------------------------------------


class TestKickWiring:
    def test_spec_kick_variables_match(self) -> None:
        assert handler._SPEC.kick_variables == {"trigger_id": "manual"}
        assert "trigger" not in handler._SPEC.kick_variables


# --------------------------------------------------------
# Schema vs blueprint drift
# --------------------------------------------------------


class TestBlueprintSchemaDrift(BlueprintSchemaDriftBase):
    """The blueprint's ``data:`` keys must match the schema."""

    handler = handler
    blueprint_filename = "battery_watchdog.yaml"


class TestBlueprintDefaultsRoundTrip(BlueprintDefaultsRoundTripBase):
    """Blueprint input defaults must satisfy the schema."""

    handler = handler
    blueprint_filename = "battery_watchdog.yaml"
    template_defaults: ClassVar = {
        "instance_id": "automation.bw_default_check",
        "trigger_id": "manual",
    }


class TestArgparseGuards(HandlerArgparseGuardsBase):
    """Schema rejection must short-circuit argparse."""

    handler = handler
    valid_payload = _valid_argparse_payload()


if __name__ == "__main__":
    from conftest import run_tests

    # ``-p no:pytest_homeassistant`` disables Home Assistant's pytest
    # plugin, which fails to import against this file's stubbed
    # ``homeassistant`` modules; the package is a mypy-only dep here.
    run_tests(
        __file__,
        _SCRIPT_PATH,
        REPO_ROOT,
        pytest_args=["-p", "no:pytest_homeassistant"],
    )
