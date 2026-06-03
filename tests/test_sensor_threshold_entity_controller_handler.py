#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-asyncio",
#     "pytest-cov",
#     "voluptuous",
#     "PyYAML",
#     "pytest-homeassistant-custom-component==0.13.331",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Unit tests for ``sensor_threshold_entity_controller.handler``.

Covers the parts that don't require booting HA: mutator
callbacks, ``_ensure_timer`` arming, ``_async_kick_for_recovery``
+ periodic-callback payload shape (``trigger_id`` AND
``trigger_entity`` must be flat top-level variables, no
``context=`` propagation), schema-level validation of the
numeric inputs, and the blueprint <-> schema drift check.
The argparse cross-field check on
``controlled_entities`` existence + the service layer's
full state-load / action-dispatch / response-shape loop
are exercised in
``test_sensor_threshold_entity_controller_integration.py``
against the pytest-HACC harness.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
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

from custom_components.blueprint_toolkit.sensor_threshold_entity_controller import (  # noqa: E402, E501
    handler,
)


def _make_state(
    instance_id: str = "automation.stec_test",
    *,
    cancel_timer: Callable[[], None] | None = None,
) -> handler.StecInstanceState:
    return handler.StecInstanceState(
        instance_id=instance_id,
        cancel_timer=cancel_timer,
    )


def _hass_with_instances(
    instances: dict[str, handler.StecInstanceState],
) -> MockHass:
    h = MockHass()
    entry = MockEntry()
    entry.runtime_data.handlers["sensor_threshold_entity_controller"] = {
        "instances": instances,
        "unsubs": [],
    }
    h.config_entries.entries.append(entry)
    return h


# --------------------------------------------------------
# Mutator callbacks
# --------------------------------------------------------


class TestOnReload:
    def test_cancels_pending_timers(self) -> None:
        canceled: list[int] = []

        s1 = _make_state(
            "automation.a",
            cancel_timer=lambda: canceled.append(1),
        )
        s2 = _make_state("automation.b")
        h = _hass_with_instances({"automation.a": s1, "automation.b": s2})

        handler._on_reload(h)

        assert canceled == [1]
        assert s1.cancel_timer is None
        assert s2.cancel_timer is None
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "sensor_threshold_entity_controller"
        ]
        assert set(bucket["instances"]) == {"automation.a", "automation.b"}


class TestOnEntityRemove:
    def test_drops_state_and_cancels_timer(self) -> None:
        canceled: list[int] = []
        s = _make_state(
            "automation.a",
            cancel_timer=lambda: canceled.append(1),
        )
        h = _hass_with_instances(
            {"automation.a": s, "automation.b": _make_state("automation.b")}
        )

        handler._on_entity_remove(h, "automation.a")

        assert canceled == [1]
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "sensor_threshold_entity_controller"
        ]
        assert set(bucket["instances"]) == {"automation.b"}

    def test_unknown_id_is_noop(self) -> None:
        h = _hass_with_instances({"automation.a": _make_state("automation.a")})
        handler._on_entity_remove(h, "automation.unknown")


class TestOnEntityRename:
    def test_moves_state_to_new_id(self) -> None:
        s = _make_state("automation.old")
        h = _hass_with_instances({"automation.old": s})

        handler._on_entity_rename(h, "automation.old", "automation.new")

        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "sensor_threshold_entity_controller"
        ]
        assert "automation.old" not in bucket["instances"]
        assert bucket["instances"]["automation.new"] is s
        assert s.instance_id == "automation.new"

    def test_unknown_old_id_is_noop(self) -> None:
        h = _hass_with_instances({})
        handler._on_entity_rename(h, "automation.x", "automation.y")


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
        bucket = h.config_entries.entries[0].runtime_data.handlers[
            "sensor_threshold_entity_controller"
        ]
        assert bucket["instances"] == {}


# --------------------------------------------------------
# _ensure_timer
# --------------------------------------------------------


class TestEnsureTimer:
    def setup_method(self) -> None:
        self.calls: list[dict[str, Any]] = []

        def _fake_schedule(
            _hass: Any,
            entry: Any,
            *,
            interval: timedelta,
            instance_id: str,
            action: Any,
        ) -> Callable[[], None]:
            self.calls.append(
                {
                    "entry": entry,
                    "interval": interval,
                    "instance_id": instance_id,
                    "action": action,
                }
            )

            return lambda: None

        self._real_schedule = handler.schedule_periodic_with_jitter
        handler.schedule_periodic_with_jitter = _fake_schedule  # type: ignore[assignment]

    def teardown_method(self) -> None:
        handler.schedule_periodic_with_jitter = self._real_schedule

    def test_first_call_arms_minute_interval(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.stec")
        e = object()

        handler._ensure_timer(h, e, s)  # type: ignore[arg-type]

        assert len(self.calls) == 1
        assert self.calls[0]["entry"] is e
        # STEC's interval is fixed at 1 minute; no
        # blueprint input controls it.
        assert self.calls[0]["interval"] == timedelta(minutes=1)
        assert self.calls[0]["instance_id"] == "automation.stec"
        assert s.cancel_timer is not None

    def test_subsequent_calls_are_noop(self) -> None:
        h = _hass_with_instances({})
        s = _make_state("automation.stec")
        e = object()
        handler._ensure_timer(h, e, s)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s)  # type: ignore[arg-type]
        handler._ensure_timer(h, e, s)  # type: ignore[arg-type]

        # Once armed, ``_ensure_timer`` is a no-op until
        # ``cancel_timer`` is reset (e.g. by ``_on_reload``
        # or ``_on_teardown``).
        assert len(self.calls) == 1


# --------------------------------------------------------
# Argparse harness
# --------------------------------------------------------


def _valid_argparse_payload(**overrides: Any) -> dict[str, Any]:
    """Return a schema-valid raw payload with optional overrides."""
    payload = {
        "instance_id": "automation.stec_test",
        "trigger_id": "manual",
        "controlled_entities_raw": ["switch.fan"],
        "sensor_value": "55.0",
        "trigger_entity": "sensor.humidity",
        "trigger_threshold_raw": 70.0,
        "release_threshold_raw": 60.0,
        "sampling_window_seconds_raw": 600,
        "disable_window_seconds_raw": 30,
        "auto_off_minutes_raw": 60,
        "notification_prefix": "",
        "notification_suffix": "",
        "debug_logging_raw": False,
    }
    payload.update(overrides)
    return payload


class _ArgparseHarness:
    """Shared setup/teardown for argparse-only tests."""

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


# --------------------------------------------------------
# Argparse: int + float input rejection (schema-level)
# --------------------------------------------------------
#
# Schema-level validation:
# ``vol.All(vol.Coerce(int), vol.Range(min=..., max=...))``
# rejects non-numeric and out-of-range integers; rejections
# flow through ``vol.MultipleInvalid`` and surface as a
# config-error notification carrying the offending field
# name (the ``schema:`` prefix the helper prepends).


class TestArgparseSchemaRejection(_ArgparseHarness):
    def test_non_numeric_threshold_rejected(self) -> None:
        import asyncio

        h = MockHass()
        # Add target_switch state so the cross-field check
        # passes; we want the schema-level rejection to be
        # the only error.
        h.states_get = {  # type: ignore[attr-defined]
            "switch.fan": object(),
        }
        h.states = type(  # type: ignore[attr-defined]
            "S",
            (),
            {"get": lambda _self, _eid: object()},
        )()
        call = FakeServiceCall(
            _valid_argparse_payload(
                trigger_threshold_raw="not-a-number",
            ),
        )
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.capture.calls == [], (
            "service layer must NOT run when schema rejects an input"
        )
        assert len(self.config_errors) == 1
        joined = "\n".join(self.config_errors[0])
        assert "trigger_threshold_raw" in joined

    def test_out_of_range_sampling_window_rejected(self) -> None:
        import asyncio

        h = MockHass()
        h.states = type(  # type: ignore[attr-defined]
            "S",
            (),
            {"get": lambda _self, _eid: object()},
        )()
        call = FakeServiceCall(
            _valid_argparse_payload(
                sampling_window_seconds_raw=99999,
            ),
        )
        asyncio.run(handler._async_argparse(h, call, now=FrozenNow.value))  # type: ignore[arg-type]

        assert self.capture.calls == []
        assert len(self.config_errors) == 1
        joined = "\n".join(self.config_errors[0])
        assert "sampling_window_seconds_raw" in joined
        assert "at most 3600" in joined


# --------------------------------------------------------
# Restart-recovery kick payload
# --------------------------------------------------------


class TestKickWiring:
    def test_spec_kick_variables_match(self) -> None:
        # STEC's kick payload includes ``trigger_entity``
        # because the blueprint's reactive triggers don't
        # carry a default; the synthetic kick supplies the
        # "timer" sentinel so the logic module's
        # event-type determination has the right input.
        assert handler._SPEC.kick_variables == {
            "trigger_id": "manual",
            "trigger_entity": "timer",
        }


# --------------------------------------------------------
# Schema vs blueprint drift
# --------------------------------------------------------


class TestBlueprintSchemaDrift(BlueprintSchemaDriftBase):
    """The blueprint's ``data:`` keys must match the schema."""

    handler = handler
    blueprint_filename = "sensor_threshold_entity_controller.yaml"


class TestBlueprintDefaultsRoundTrip(BlueprintDefaultsRoundTripBase):
    """Blueprint input defaults must satisfy the schema."""

    handler = handler
    blueprint_filename = "sensor_threshold_entity_controller.yaml"
    template_defaults = {
        "instance_id": "automation.stec_default_check",
        "trigger_id": "manual",
        "controlled_entities_raw": ["switch.fan"],
        "sensor_value": "0",
        "trigger_entity": "sensor.humidity",
    }


class TestArgparseGuards(HandlerArgparseGuardsBase):
    """Schema rejection must short-circuit argparse.

    The unregistered-notify-service guard auto-skips
    because STEC's schema no longer carries a
    ``notification_service`` field -- notify dispatch is
    owned by the blueprint via ``response_variable`` /
    ``notify_action`` rather than by the handler.
    """

    handler = handler
    valid_payload = _valid_argparse_payload()


if __name__ == "__main__":
    # ``-p no:homeassistant`` disables pytest-HACC's plugin,
    # which fails to import against this file's stubbed
    # ``homeassistant`` modules; HACC is a mypy-only dep here.
    sys.exit(
        pytest.main([__file__, "-v", "-p", "no:homeassistant", *sys.argv[1:]])
    )
