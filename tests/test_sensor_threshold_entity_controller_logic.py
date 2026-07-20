#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest",
#     "pytest-cov",
#     "pytest-homeassistant-custom-component==0.13.346",
#     "types-PyYAML",
# ]
# ///
# This is AI generated code
"""Tests for sensor_threshold_entity_controller logic.

The controlled set is multi-entity. ``ON`` (or ``"on"``)
helpers build the ``controlled_on_entities`` list; a single
controlled entity (N=1) is the common case and must behave
exactly as a single-switch controller did. The N=2 cases lock
down any-on aggregation plus the turn-OFF "report only the
on-subset" contract.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict, Unpack

REPO_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from custom_components.blueprint_toolkit.sensor_threshold_entity_controller.logic import (  # noqa: E402, E501
    Action,
    Config,
    Controller,
    EventType,
    Inputs,
    Result,
    Sample,
    ServiceResult,
    State,
    determine_event_type,
    evaluate,
    handle_service_call,
    parse_float,
)

T0 = datetime(2024, 1, 15, 12, 0, 0)

# The single controlled entity used by the N=1 parity tests.
SW = "switch.fan"
# Second controlled entity for the N=2 aggregation tests.
SW2 = "switch.fan2"


def _on_list(controlled_on: bool) -> list[str]:
    """Map a boolean "is on" to the single-entity on-subset."""
    return [SW] if controlled_on else []


def sensor_inputs(
    value: float | None,
    controlled_on: bool = False,
    current_time: datetime = T0,
    controlled_on_entities: list[str] | None = None,
    friendly_names: dict[str, str] | None = None,
) -> Inputs:
    """Build Inputs for a sensor event.

    ``controlled_on`` is the N=1 convenience; pass
    ``controlled_on_entities`` directly for N>1.
    """
    if controlled_on_entities is None:
        controlled_on_entities = _on_list(controlled_on)
    return Inputs(
        current_time=current_time,
        event_type=EventType.SENSOR,
        sensor_value=value,
        controlled_on_entities=controlled_on_entities,
        friendly_names=friendly_names or {},
    )


def switch_inputs(
    controlled_on: bool,
    current_time: datetime = T0,
    controlled_on_entities: list[str] | None = None,
    friendly_names: dict[str, str] | None = None,
) -> Inputs:
    """Build Inputs for a controlled-entity event."""
    if controlled_on_entities is None:
        controlled_on_entities = _on_list(controlled_on)
    return Inputs(
        current_time=current_time,
        event_type=EventType.SWITCH,
        controlled_on_entities=controlled_on_entities,
        friendly_names=friendly_names or {},
    )


def timer_inputs(
    controlled_on: bool = True,
    current_time: datetime = T0,
    controlled_on_entities: list[str] | None = None,
    friendly_names: dict[str, str] | None = None,
) -> Inputs:
    """Build Inputs for a timer event."""
    if controlled_on_entities is None:
        controlled_on_entities = _on_list(controlled_on)
    return Inputs(
        current_time=current_time,
        event_type=EventType.TIMER,
        controlled_on_entities=controlled_on_entities,
        friendly_names=friendly_names or {},
    )


def _config(
    *,
    controlled_entities: list[str] | None = None,
    trigger_threshold: float = 5.0,
    release_threshold: float = 2.0,
    sampling_window_seconds: int = 120,
    disable_window_seconds: int = 10,
    auto_off_minutes: int = 1,
) -> Config:
    return Config(
        controlled_entities=(
            [SW] if controlled_entities is None else controlled_entities
        ),
        trigger_threshold=trigger_threshold,
        release_threshold=release_threshold,
        sampling_window_seconds=sampling_window_seconds,
        disable_window_seconds=disable_window_seconds,
        auto_off_minutes=auto_off_minutes,
    )


class TestParseFloat:
    def test_valid_float(self) -> None:
        assert parse_float("42.5") == 42.5

    def test_integer_string(self) -> None:
        assert parse_float("42") == 42.0

    def test_none_returns_none(self) -> None:
        assert parse_float(None) is None

    def test_empty_string(self) -> None:
        assert parse_float("") is None

    def test_unknown(self) -> None:
        assert parse_float("unknown") is None

    def test_unavailable(self) -> None:
        assert parse_float("unavailable") is None

    def test_nan_string(self) -> None:
        assert parse_float("NaN") is None

    def test_inf_string(self) -> None:
        assert parse_float("inf") is None

    def test_negative_inf(self) -> None:
        assert parse_float("-inf") is None

    def test_non_numeric_text(self) -> None:
        assert parse_float("hello") is None

    def test_negative_number(self) -> None:
        assert parse_float("-3.14") == -3.14

    def test_zero(self) -> None:
        assert parse_float("0") == 0.0


class TestStateSerialization:
    def test_empty_state_round_trip(self) -> None:
        state = State()
        data = state.to_dict()
        restored = State.from_dict(data)
        assert restored.samples == []
        assert restored.baseline is None
        assert restored.overrides == []
        assert restored.auto_off_started_at is None
        assert restored.initialized is False

    def test_populated_state_round_trip(self) -> None:
        state = State(
            samples=[Sample(value=60.0, timestamp=T0)],
            baseline=55.0,
            overrides=[T0],
            auto_off_started_at=T0,
            initialized=True,
        )
        data = state.to_dict()
        restored = State.from_dict(data)
        assert len(restored.samples) == 1
        assert restored.samples[0].value == 60.0
        assert restored.samples[0].timestamp == T0
        assert restored.baseline == 55.0
        assert restored.overrides == [T0]
        assert restored.auto_off_started_at == T0
        assert restored.initialized is True

    def test_from_dict_missing_keys(self) -> None:
        restored = State.from_dict({})
        assert restored.samples == []
        assert restored.baseline is None
        assert restored.overrides == []
        assert restored.auto_off_started_at is None
        assert restored.initialized is False

    def test_realistic_state_exceeds_ha_state_limit(
        self,
    ) -> None:
        """Serialized state with samples exceeds the HA
        entity state value limit of 255 characters.

        This is why the service wrapper stores state in an
        entity attribute (via state.setattr) rather than the
        entity state value (via state.set).  If someone
        changes the storage mechanism back to state.set,
        persistence will silently fail once enough sensor
        readings accumulate.

        5 samples is modest (300s window, reading every 60s).
        """
        state = State(
            samples=[
                Sample(
                    value=65.0 + i,
                    timestamp=T0 + timedelta(seconds=60 * i),
                )
                for i in range(5)
            ],
            baseline=60.0,
            overrides=[T0],
            auto_off_started_at=T0,
            initialized=True,
        )
        serialized = json.dumps(state.to_dict())
        assert len(serialized) > 255, (
            f"Serialized state is only {len(serialized)}"
            " chars. If a refactor shrinks it below 255,"
            " update the service wrapper comment and"
            " consider whether attribute storage is"
            " still needed."
        )


class TestInputsControlledOn:
    def test_empty_list_is_off(self) -> None:
        assert switch_inputs(False).controlled_on is False

    def test_one_on_is_on(self) -> None:
        assert switch_inputs(True).controlled_on is True

    def test_any_on_aggregation(self) -> None:
        """controlled_on is True if ANY entity is on."""
        i = switch_inputs(True, controlled_on_entities=[SW2])
        assert i.controlled_on is True


class TestSensorSpikeDetection:
    @pytest.fixture()
    def controller(self) -> Controller:
        return Controller(_config())

    def test_no_action_for_none_sensor_value(
        self, controller: Controller
    ) -> None:
        state = State()
        result = controller.evaluate(state, sensor_inputs(None))
        assert result.action == Action.NONE
        assert state.samples == []

    def test_no_trigger_below_threshold(self, controller: Controller) -> None:
        state = State()
        controller.evaluate(state, sensor_inputs(60.0))
        result = controller.evaluate(state, sensor_inputs(64.0))
        assert result.action == Action.NONE
        assert state.baseline is None

    def test_no_trigger_at_exact_threshold(
        self, controller: Controller
    ) -> None:
        """Spike must be strictly greater than threshold."""
        state = State()
        controller.evaluate(state, sensor_inputs(60.0))
        result = controller.evaluate(state, sensor_inputs(65.0))
        assert result.action == Action.NONE
        assert state.baseline is None

    def test_trigger_above_threshold(self, controller: Controller) -> None:
        state = State()
        controller.evaluate(state, sensor_inputs(60.0))
        result = controller.evaluate(state, sensor_inputs(65.1))
        assert result.action == Action.TURN_ON
        assert result.target_entities == [SW]
        assert state.baseline == 60.0
        assert "spike" in result.reason.lower()
        assert result.notification != ""

    def test_sets_baseline_to_min_on_spike(
        self, controller: Controller
    ) -> None:
        state = State()
        controller.evaluate(state, sensor_inputs(60.0))
        controller.evaluate(state, sensor_inputs(58.0))
        result = controller.evaluate(state, sensor_inputs(70.0))
        assert result.action == Action.TURN_ON
        assert state.baseline == 58.0

    def test_spike_clears_overrides_and_auto_off(
        self, controller: Controller
    ) -> None:
        state = State(
            overrides=[T0],
            auto_off_started_at=T0,
        )
        controller.evaluate(state, sensor_inputs(60.0))
        controller.evaluate(state, sensor_inputs(70.0))
        assert state.overrides == []
        assert state.auto_off_started_at is None

    def test_spike_when_already_on(self, controller: Controller) -> None:
        """When the set is already on, set baseline but
        don't command TURN_ON."""
        state = State()
        controller.evaluate(
            state,
            sensor_inputs(60.0, controlled_on=True),
        )
        result = controller.evaluate(
            state,
            sensor_inputs(70.0, controlled_on=True),
        )
        assert result.action == Action.NONE
        assert state.baseline == 60.0
        assert result.notification == ""


class TestSensorRelease:
    @pytest.fixture()
    def controller(self) -> Controller:
        return Controller(_config(auto_off_minutes=30))

    def test_no_release_above_threshold(self, controller: Controller) -> None:
        state = State(baseline=60.0)
        result = controller.evaluate(
            state,
            sensor_inputs(65.0, controlled_on=True),
        )
        assert result.action == Action.NONE
        assert state.baseline == 60.0

    def test_release_at_threshold_boundary(
        self, controller: Controller
    ) -> None:
        """Release when max <= baseline + release."""
        state = State(baseline=60.0)
        result = controller.evaluate(
            state,
            sensor_inputs(62.0, controlled_on=True),
        )
        assert result.action == Action.TURN_OFF
        assert result.target_entities == [SW]
        assert state.baseline is None
        assert "release" in result.reason.lower()
        assert result.notification != ""

    def test_release_clears_state(self, controller: Controller) -> None:
        state = State(
            baseline=60.0,
            overrides=[T0],
            auto_off_started_at=T0,
        )
        controller.evaluate(
            state,
            sensor_inputs(61.0, controlled_on=True),
        )
        assert state.baseline is None
        assert state.overrides == []
        assert state.auto_off_started_at is None

    def test_release_when_already_off(self, controller: Controller) -> None:
        state = State(baseline=60.0)
        result = controller.evaluate(
            state,
            sensor_inputs(62.0, controlled_on=False),
        )
        assert result.action == Action.NONE
        assert state.baseline is None
        assert result.notification == ""


class TestSampleWindow:
    @pytest.fixture()
    def controller(self) -> Controller:
        return Controller(_config(sampling_window_seconds=10))

    def test_prunes_old_samples(self, controller: Controller) -> None:
        now = T0
        state = State(
            samples=[
                Sample(
                    value=50.0,
                    timestamp=now - timedelta(seconds=15),
                ),
                Sample(
                    value=60.0,
                    timestamp=now - timedelta(seconds=5),
                ),
                Sample(
                    value=70.0,
                    timestamp=now - timedelta(seconds=1),
                ),
            ]
        )
        controller.evaluate(
            state,
            sensor_inputs(65.0, current_time=now),
        )
        # Old sample (15s ago) pruned; 3 remain
        assert len(state.samples) == 3
        values = [s.value for s in state.samples]
        assert 50.0 not in values
        assert 60.0 in values
        assert 70.0 in values
        assert 65.0 in values


class TestManualOverride:
    @pytest.fixture()
    def controller(self) -> Controller:
        return Controller(_config(sampling_window_seconds=300))

    def test_re_enables_on_first_manual_off(
        self, controller: Controller
    ) -> None:
        state = State(
            baseline=55.0,
            initialized=True,
        )
        result = controller.evaluate(state, switch_inputs(False))
        assert result.action == Action.TURN_ON
        assert result.target_entities == [SW]
        assert len(state.overrides) == 1
        assert "manual off" in result.reason.lower()
        assert result.notification != ""

    def test_disables_on_double_manual_off(
        self, controller: Controller
    ) -> None:
        state = State(
            baseline=55.0,
            initialized=True,
            overrides=[T0 - timedelta(seconds=5)],
        )
        result = controller.evaluate(state, switch_inputs(False))
        assert result.action == Action.NONE
        assert state.baseline is None
        assert "override disabled" in result.notification
        assert state.overrides == []

    def test_no_disable_outside_window(self, controller: Controller) -> None:
        """Second off 20s ago, outside 10s window."""
        state = State(
            baseline=55.0,
            initialized=True,
            overrides=[T0 - timedelta(seconds=20)],
        )
        result = controller.evaluate(state, switch_inputs(False))
        assert result.action == Action.TURN_ON
        assert state.baseline == 55.0

    def test_disable_window_zero_never_disables(
        self,
    ) -> None:
        """When disable_window=0, always re-enable."""
        ctrl = Controller(
            _config(
                sampling_window_seconds=300,
                disable_window_seconds=0,
                auto_off_minutes=30,
            )
        )
        state = State(
            baseline=55.0,
            initialized=True,
            overrides=[T0 - timedelta(seconds=1)],
        )
        result = ctrl.evaluate(state, switch_inputs(False))
        assert result.action == Action.TURN_ON
        # Previous overrides cleared, only current one
        assert len(state.overrides) == 1


class TestAutoOff:
    @pytest.fixture()
    def controller(self) -> Controller:
        return Controller(_config(sampling_window_seconds=300))

    def test_schedules_on_manual_on(self, controller: Controller) -> None:
        state = State(initialized=True)
        controller.evaluate(state, switch_inputs(True))
        assert state.auto_off_started_at == T0

    def test_timer_fires_after_timeout(self, controller: Controller) -> None:
        state = State(
            auto_off_started_at=T0,
            initialized=True,
        )
        result = controller.evaluate(
            state,
            timer_inputs(current_time=T0 + timedelta(minutes=1)),
        )
        assert result.action == Action.TURN_OFF
        assert result.target_entities == [SW]
        assert state.auto_off_started_at is None
        assert "auto-off" in result.reason.lower()
        assert result.notification != ""

    def test_timer_no_action_before_timeout(
        self, controller: Controller
    ) -> None:
        state = State(
            auto_off_started_at=T0,
            initialized=True,
        )
        result = controller.evaluate(
            state,
            timer_inputs(current_time=T0 + timedelta(seconds=30)),
        )
        assert result.action == Action.NONE
        assert state.auto_off_started_at == T0

    def test_timer_ignored_when_baseline_active(
        self, controller: Controller
    ) -> None:
        state = State(
            auto_off_started_at=T0,
            baseline=55.0,
            initialized=True,
        )
        result = controller.evaluate(
            state,
            timer_inputs(current_time=T0 + timedelta(minutes=5)),
        )
        assert result.action == Action.NONE
        assert state.auto_off_started_at == T0

    def test_timer_ignored_when_off(self, controller: Controller) -> None:
        state = State(
            auto_off_started_at=T0,
            initialized=True,
        )
        result = controller.evaluate(
            state,
            timer_inputs(
                controlled_on=False,
                current_time=T0 + timedelta(minutes=5),
            ),
        )
        assert result.action == Action.NONE

    def test_cancelled_when_baseline_set(self, controller: Controller) -> None:
        """Auto-off cancelled when sensor spike takes
        over control."""
        state = State(
            auto_off_started_at=T0,
            initialized=True,
        )
        # Sensor spike: baseline gets set
        controller.evaluate(
            state,
            sensor_inputs(60.0, controlled_on=True),
        )
        controller.evaluate(
            state,
            sensor_inputs(70.0, controlled_on=True),
        )
        assert state.baseline == 60.0
        assert state.auto_off_started_at is None

    def test_cancelled_on_off_no_baseline(self, controller: Controller) -> None:
        state = State(
            auto_off_started_at=T0,
            initialized=True,
        )
        controller.evaluate(state, switch_inputs(False))
        assert state.auto_off_started_at is None

    def test_cleared_on_on_with_baseline(self, controller: Controller) -> None:
        """When the set turns on while baseline active,
        auto-off is cancelled."""
        state = State(
            baseline=55.0,
            auto_off_started_at=T0,
            initialized=True,
        )
        controller.evaluate(state, switch_inputs(True))
        assert state.auto_off_started_at is None

    def test_auto_off_zero_disables(self) -> None:
        """auto_off_minutes=0 means no auto-off."""
        ctrl = Controller(
            _config(sampling_window_seconds=300, auto_off_minutes=0)
        )
        state = State(initialized=True)
        ctrl.evaluate(state, switch_inputs(True))
        assert state.auto_off_started_at is None


class TestMultiEntityAggregation:
    """N=2 controlled set: any-on aggregation + the turn-OFF
    "report only the on-subset" contract."""

    @pytest.fixture()
    def controller(self) -> Controller:
        return Controller(
            _config(
                controlled_entities=[SW, SW2],
                sampling_window_seconds=300,
                auto_off_minutes=1,
            )
        )

    def test_spike_turns_on_full_list(self, controller: Controller) -> None:
        """A spike targets every configured entity."""
        state = State()
        controller.evaluate(
            state,
            sensor_inputs(60.0, controlled_on_entities=[]),
        )
        result = controller.evaluate(
            state,
            sensor_inputs(70.0, controlled_on_entities=[]),
        )
        assert result.action == Action.TURN_ON
        assert result.target_entities == [SW, SW2]

    def test_release_targets_only_on_subset(
        self, controller: Controller
    ) -> None:
        """Two controlled entities, only one on -> release
        turns OFF and targets / names just the on-subset."""
        state = State(baseline=60.0)
        result = controller.evaluate(
            state,
            sensor_inputs(
                62.0,
                controlled_on_entities=[SW2],
                friendly_names={SW: "Fan One", SW2: "Fan Two"},
            ),
        )
        assert result.action == Action.TURN_OFF
        assert result.target_entities == [SW2]
        # Notification names only the on-subset.
        assert "Fan Two" in result.notification
        assert "Fan One" not in result.notification

    def test_auto_off_targets_only_on_subset(
        self, controller: Controller
    ) -> None:
        """Auto-off expiry turns OFF and names only the
        subset that is currently on."""
        state = State(
            auto_off_started_at=T0,
            initialized=True,
        )
        result = controller.evaluate(
            state,
            timer_inputs(
                current_time=T0 + timedelta(minutes=1),
                controlled_on_entities=[SW2],
                friendly_names={SW: "Fan One", SW2: "Fan Two"},
            ),
        )
        assert result.action == Action.TURN_OFF
        assert result.target_entities == [SW2]
        assert "Fan Two" in result.notification
        assert "Fan One" not in result.notification

    def test_release_on_subset_order_preserved(
        self, controller: Controller
    ) -> None:
        """The on-subset preserves the caller's order."""
        state = State(baseline=60.0)
        result = controller.evaluate(
            state,
            sensor_inputs(
                62.0,
                controlled_on_entities=[SW, SW2],
            ),
        )
        assert result.target_entities == [SW, SW2]

    def test_any_on_keeps_baseline_managing(
        self, controller: Controller
    ) -> None:
        """With one entity on, a spike does not re-command
        TURN_ON (the set is already considered on)."""
        state = State()
        controller.evaluate(
            state,
            sensor_inputs(60.0, controlled_on_entities=[SW2]),
        )
        result = controller.evaluate(
            state,
            sensor_inputs(70.0, controlled_on_entities=[SW2]),
        )
        assert result.action == Action.NONE
        assert state.baseline == 60.0


class TestStartupRecovery:
    @pytest.fixture()
    def controller(self) -> Controller:
        return Controller(_config(sampling_window_seconds=300))

    def test_startup_on_schedules_auto_off(
        self, controller: Controller
    ) -> None:
        state = State(initialized=False)
        result = controller.evaluate(state, switch_inputs(True))
        assert result.action == Action.NONE
        assert state.initialized is True
        assert state.auto_off_started_at == T0

    def test_startup_off_no_auto_off(self, controller: Controller) -> None:
        state = State(initialized=False)
        result = controller.evaluate(state, switch_inputs(False))
        assert result.action == Action.NONE
        assert state.initialized is True
        assert state.auto_off_started_at is None

    def test_startup_with_baseline_no_auto_off(
        self, controller: Controller
    ) -> None:
        """If baseline is active at startup, no auto-off
        (sensor is managing)."""
        state = State(initialized=False, baseline=55.0)
        controller.evaluate(state, switch_inputs(True))
        assert state.auto_off_started_at is None

    def test_startup_returns_no_action(self, controller: Controller) -> None:
        """First switch event always returns NONE."""
        state = State(initialized=False)
        result = controller.evaluate(state, switch_inputs(True))
        assert result.action == Action.NONE

    def test_timer_starts_auto_off_when_on_no_state(
        self, controller: Controller
    ) -> None:
        """After HA restart with lost state, the first timer
        event should start auto-off if the set is already on."""
        state = State()  # fresh state, no auto_off_started_at
        t = T0

        result = controller.evaluate(state, timer_inputs(True, current_time=t))
        assert result.action == Action.NONE
        assert state.auto_off_started_at == t

        # After timeout, timer should turn off.
        t += timedelta(minutes=1, seconds=1)
        result = controller.evaluate(state, timer_inputs(True, current_time=t))
        assert result.action == Action.TURN_OFF

    def test_timer_no_auto_off_when_off(self, controller: Controller) -> None:
        """Timer should not start auto-off if the set is off."""
        state = State()
        result = controller.evaluate(
            state, timer_inputs(False, current_time=T0)
        )
        assert result.action == Action.NONE
        assert state.auto_off_started_at is None

    def test_timer_no_auto_off_when_baseline_active(
        self, controller: Controller
    ) -> None:
        """Timer should not start auto-off if sensor is
        managing the set (baseline active)."""
        state = State(baseline=55.0)
        result = controller.evaluate(state, timer_inputs(True, current_time=T0))
        assert result.action == Action.NONE
        assert state.auto_off_started_at is None


class TestEndToEnd:
    """Full scenario tests simulating real sequences (N=1)."""

    @pytest.fixture()
    def controller(self) -> Controller:
        return Controller(
            _config(
                trigger_threshold=10.0,
                release_threshold=5.0,
                sampling_window_seconds=300,
                auto_off_minutes=30,
            )
        )

    def test_humidity_fan_cycle(self, controller: Controller) -> None:
        """Full cycle: startup -> humidity spike ->
        fan on -> humidity drops -> fan off."""
        state = State()
        t = T0

        # Startup: set is off
        controller.evaluate(state, switch_inputs(False, current_time=t))
        assert state.initialized is True

        # Humidity readings (stable)
        for i in range(3):
            t += timedelta(seconds=30)
            controller.evaluate(
                state,
                sensor_inputs(
                    50.0 + i * 0.5,
                    current_time=t,
                ),
            )
        assert state.baseline is None

        # Shower starts: humidity spikes
        t += timedelta(seconds=30)
        result = controller.evaluate(
            state,
            sensor_inputs(62.0, current_time=t),
        )
        assert result.action == Action.TURN_ON
        assert result.target_entities == [SW]
        assert state.baseline == 50.0

        # Humidity stays high, timer ticks
        for _ in range(5):
            t += timedelta(minutes=1)
            result = controller.evaluate(
                state,
                timer_inputs(
                    controlled_on=True,
                    current_time=t,
                ),
            )
            assert result.action == Action.NONE

        # Humidity drops back to normal
        t += timedelta(minutes=1)
        result = controller.evaluate(
            state,
            sensor_inputs(
                54.0,
                controlled_on=True,
                current_time=t,
            ),
        )
        assert result.action == Action.TURN_OFF
        assert result.target_entities == [SW]
        assert state.baseline is None

    def test_manual_on_auto_off_cycle(self, controller: Controller) -> None:
        """Manual on -> timer ticks -> auto-off fires."""
        state = State()
        t = T0

        # Startup
        controller.evaluate(state, switch_inputs(False, current_time=t))

        # Manual on
        t += timedelta(seconds=5)
        controller.evaluate(state, switch_inputs(True, current_time=t))
        # Rounded up to next minute for time_pattern alignment
        assert state.auto_off_started_at == t.replace(
            second=0,
            microsecond=0,
        ) + timedelta(minutes=1)

        # Timer ticks for 30 minutes (extra minute from round-up)
        for _ in range(30):
            t += timedelta(minutes=1)
            result = controller.evaluate(
                state,
                timer_inputs(current_time=t),
            )
            assert result.action == Action.NONE

        # 31 minutes: auto-off fires (30 min timeout + round-up)
        t += timedelta(minutes=1)
        result = controller.evaluate(
            state,
            timer_inputs(current_time=t),
        )
        assert result.action == Action.TURN_OFF

    def test_manual_off_override_and_disable(
        self, controller: Controller
    ) -> None:
        """Baseline active -> manual off -> re-enable ->
        manual off again -> disable."""
        state = State(baseline=50.0, initialized=True)
        t = T0

        # First manual off: re-enable
        result = controller.evaluate(
            state, switch_inputs(False, current_time=t)
        )
        assert result.action == Action.TURN_ON

        # Second manual off within window: disable
        t += timedelta(seconds=5)
        result = controller.evaluate(
            state, switch_inputs(False, current_time=t)
        )
        assert result.action == Action.NONE
        assert state.baseline is None
        assert "disabled" in result.notification


class TestConfigValidation:
    def test_all_fields_required(self) -> None:
        """Config has no defaults; all fields must be given."""
        with pytest.raises(TypeError):
            Config()  # type: ignore[call-arg]

    def test_custom_config(self) -> None:
        config = Config(
            controlled_entities=[SW],
            trigger_threshold=10.0,
            release_threshold=3.0,
            sampling_window_seconds=600,
            disable_window_seconds=0,
            auto_off_minutes=0,
        )
        assert config.trigger_threshold == 10.0
        assert config.auto_off_minutes == 0
        assert config.controlled_entities == [SW]


class TestResultDefaults:
    def test_default_result(self) -> None:
        result = Result()
        assert result.action == Action.NONE
        assert result.target_entities == []
        assert result.reason == ""
        assert result.notification == ""


class TestUnknownEventType:
    def test_returns_none_for_unknown(self) -> None:
        """Controller.evaluate returns NONE for
        unrecognized event types, though all EventType
        values are handled."""
        ctrl = Controller(_config(sampling_window_seconds=300))
        state = State()
        inputs = Inputs(
            current_time=T0,
            event_type=EventType.TIMER,
            controlled_on_entities=[],
        )
        result = ctrl.evaluate(state, inputs)
        assert result.action == Action.NONE


class TestDetermineEventType:
    def test_switch_event(self) -> None:
        """Trigger entity in controlled list -> SWITCH."""
        assert determine_event_type("switch.fan", ["switch.fan"]) == (
            EventType.SWITCH
        )

    def test_switch_event_multi(self) -> None:
        """Any member of the controlled list -> SWITCH."""
        assert determine_event_type(SW2, [SW, SW2]) == EventType.SWITCH

    def test_sensor_event(self) -> None:
        """Trigger entity not in controlled list -> SENSOR."""
        assert (
            determine_event_type("sensor.humidity", ["switch.fan"])
            == EventType.SENSOR
        )

    def test_timer_empty_string(self) -> None:
        assert determine_event_type("", ["switch.fan"]) == EventType.TIMER

    def test_timer_literal_timer(self) -> None:
        assert determine_event_type("timer", ["switch.fan"]) == EventType.TIMER

    def test_timer_literal_none(self) -> None:
        assert determine_event_type("None", ["switch.fan"]) == EventType.TIMER

    def test_timer_lowercase_none(self) -> None:
        assert determine_event_type("none", ["switch.fan"]) == EventType.TIMER


class _EvalKwargs(TypedDict):
    """The non-``state`` keyword arguments of ``evaluate()``."""

    current_time: datetime
    controlled_entities: list[str]
    controlled_on_entities: list[str]
    friendly_names: dict[str, str]
    sensor_value: str
    trigger_entity: str
    trigger_threshold: float
    release_threshold: float
    sampling_window_seconds: int
    disable_window_seconds: int
    auto_off_minutes: int
    notification_prefix: str
    notification_suffix: str


class _EvalKwargsOverrides(TypedDict, total=False):
    """Subset of ``_EvalKwargs`` a test may override."""

    current_time: datetime
    controlled_entities: list[str]
    controlled_on_entities: list[str]
    friendly_names: dict[str, str]
    sensor_value: str
    trigger_entity: str
    trigger_threshold: float
    release_threshold: float
    sampling_window_seconds: int
    disable_window_seconds: int
    auto_off_minutes: int
    notification_prefix: str
    notification_suffix: str


class TestEvaluate:
    """Tests for the top-level evaluate() entrypoint."""

    @staticmethod
    def _eval_kwargs(
        **overrides: Unpack[_EvalKwargsOverrides],
    ) -> _EvalKwargs:
        """Default kwargs for evaluate(), with optional per-test overrides."""
        defaults: _EvalKwargs = {
            "current_time": T0,
            "controlled_entities": [SW],
            "controlled_on_entities": [],
            "friendly_names": {},
            "sensor_value": "",
            "trigger_entity": "timer",
            "trigger_threshold": 5.0,
            "release_threshold": 2.0,
            "sampling_window_seconds": 300,
            "disable_window_seconds": 10,
            "auto_off_minutes": 30,
            "notification_prefix": "",
            "notification_suffix": "",
        }
        defaults.update(overrides)
        return defaults

    def test_sensor_spike_turns_on(self) -> None:
        """Spike -> TURN_ON with formatted notification."""
        s = State()
        # Seed a low reading first
        evaluate(
            state=s,
            **self._eval_kwargs(
                sensor_value="60.0",
                trigger_entity="sensor.humidity",
                notification_prefix="PRE: ",
                notification_suffix=" END",
            ),
        )
        result = evaluate(
            state=s,
            **self._eval_kwargs(
                sensor_value="70.0",
                trigger_entity="sensor.humidity",
                notification_prefix="PRE: ",
                notification_suffix=" END",
                current_time=T0 + timedelta(seconds=10),
            ),
        )
        assert result.action == Action.TURN_ON
        assert result.target_entities == [SW]
        assert result.notification.startswith("PRE: ")
        assert result.notification.endswith(" END")

    def test_timer_event_no_action(self) -> None:
        """Timer trigger with no auto-off -> NONE."""
        s = State()
        result = evaluate(state=s, **self._eval_kwargs())
        assert result.action == Action.NONE
        assert result.notification == ""

    def test_switch_event_startup(self) -> None:
        """Switch trigger on uninitialized state."""
        s = State()
        result = evaluate(
            state=s,
            **self._eval_kwargs(
                controlled_on_entities=[SW],
                trigger_entity="switch.fan",
                auto_off_minutes=5,
            ),
        )
        assert result.action == Action.NONE
        assert s.initialized is True
        assert s.auto_off_started_at == T0

    def test_no_notification_formatting_when_empty(
        self,
    ) -> None:
        """When controller returns no notification, prefix
        and suffix are not applied."""
        s = State()
        result = evaluate(
            state=s,
            **self._eval_kwargs(
                notification_prefix="PRE: ",
                notification_suffix=" END",
            ),
        )
        assert result.notification == ""

    def test_sensor_value_not_parsed_for_non_sensor(
        self,
    ) -> None:
        """sensor_value is ignored for non-sensor events."""
        s = State()
        result = evaluate(
            state=s,
            **self._eval_kwargs(sensor_value="99.9"),
        )
        assert result.action == Action.NONE


class _CallKwargs(TypedDict):
    """The keyword arguments of ``handle_service_call()``."""

    state_data: dict[str, Any] | None
    current_time: datetime
    controlled_entities: list[str]
    controlled_on_entities: list[str]
    friendly_names: dict[str, str]
    sensor_value: str
    trigger_entity: str
    trigger_threshold: float
    release_threshold: float
    sampling_window_seconds: int
    disable_window_seconds: int
    auto_off_minutes: int
    notification_prefix: str
    notification_suffix: str


class _CallKwargsOverrides(TypedDict, total=False):
    """Subset of ``_CallKwargs`` a test may override."""

    state_data: dict[str, Any] | None
    current_time: datetime
    controlled_entities: list[str]
    controlled_on_entities: list[str]
    friendly_names: dict[str, str]
    sensor_value: str
    trigger_entity: str
    trigger_threshold: float
    release_threshold: float
    sampling_window_seconds: int
    disable_window_seconds: int
    auto_off_minutes: int
    notification_prefix: str
    notification_suffix: str


class TestHandleServiceCall:
    """Tests for the handle_service_call bridge entry
    point."""

    @staticmethod
    def _call_kwargs(
        **overrides: Unpack[_CallKwargsOverrides],
    ) -> _CallKwargs:
        """Default kwargs for handle_service_call, with overrides."""
        defaults: _CallKwargs = {
            "state_data": None,
            "current_time": T0,
            "controlled_entities": [SW],
            "controlled_on_entities": [],
            "friendly_names": {},
            "sensor_value": "",
            "trigger_entity": "timer",
            "trigger_threshold": 5.0,
            "release_threshold": 2.0,
            "sampling_window_seconds": 300,
            "disable_window_seconds": 10,
            "auto_off_minutes": 30,
            "notification_prefix": "",
            "notification_suffix": "",
        }
        defaults.update(overrides)
        return defaults

    def test_returns_state_dict(self) -> None:
        """ServiceResult includes a serialisable
        state_dict."""
        result = handle_service_call(
            **self._call_kwargs(),
        )
        assert isinstance(result, ServiceResult)
        assert isinstance(result.state_dict, dict)

    def test_sensor_spike_returns_turn_on(self) -> None:
        """Two sensor readings that spike -> TURN_ON."""
        r1 = handle_service_call(
            **self._call_kwargs(
                sensor_value="60.0",
                trigger_entity="sensor.humidity",
                current_time=T0,
            ),
        )
        # Feed saved state back in
        r2 = handle_service_call(
            **self._call_kwargs(
                state_data=r1.state_dict,
                sensor_value="70.0",
                trigger_entity="sensor.humidity",
                current_time=T0 + timedelta(seconds=10),
            ),
        )
        assert r2.action == Action.TURN_ON
        assert r2.target_entities == [SW]

    def test_release_returns_turn_off_on_subset(self) -> None:
        """Baseline active, sensor drops -> TURN_OFF targets
        only the on-subset."""
        seed = State(
            baseline=60.0,
            samples=[Sample(value=62.0, timestamp=T0)],
            initialized=True,
        )
        result = handle_service_call(
            **self._call_kwargs(
                controlled_entities=[SW, SW2],
                controlled_on_entities=[SW2],
                state_data=seed.to_dict(),
                sensor_value="61.0",
                trigger_entity="sensor.humidity",
                current_time=T0 + timedelta(seconds=30),
            ),
        )
        assert result.action == Action.TURN_OFF
        assert result.target_entities == [SW2]

    def test_notification_message_populated_on_spike(
        self,
    ) -> None:
        """Spike -> ServiceResult.notification carries the
        formatted spike message."""
        r1 = handle_service_call(
            **self._call_kwargs(
                sensor_value="60.0",
                trigger_entity="sensor.humidity",
                current_time=T0,
            ),
        )
        r2 = handle_service_call(
            **self._call_kwargs(
                state_data=r1.state_dict,
                sensor_value="70.0",
                trigger_entity="sensor.humidity",
                current_time=T0 + timedelta(seconds=10),
            ),
        )
        assert "spike" in r2.notification.lower()

    def test_no_action_on_timer_idle(self) -> None:
        """Timer event, no auto-off pending -> NONE."""
        result = handle_service_call(
            **self._call_kwargs(),
        )
        assert result.action == Action.NONE

    def test_state_data_none_uses_fresh(self) -> None:
        """state_data=None -> no crash, state_dict
        returned."""
        result = handle_service_call(
            **self._call_kwargs(state_data=None),
        )
        assert isinstance(result.state_dict, dict)

    def test_reason_populated_on_spike(self) -> None:
        """ServiceResult.reason is set when action taken."""
        r1 = handle_service_call(
            **self._call_kwargs(
                sensor_value="60.0",
                trigger_entity="sensor.humidity",
                current_time=T0,
            ),
        )
        r2 = handle_service_call(
            **self._call_kwargs(
                state_data=r1.state_dict,
                sensor_value="70.0",
                trigger_entity="sensor.humidity",
                current_time=T0 + timedelta(seconds=10),
            ),
        )
        assert r2.reason != ""
        assert "spike" in r2.reason.lower()

    def test_reason_empty_on_no_action(self) -> None:
        """ServiceResult.reason is empty when no action."""
        result = handle_service_call(
            **self._call_kwargs(),
        )
        assert result.reason == ""

    def test_event_type_timer(self) -> None:
        """ServiceResult.event_type is TIMER for timer."""
        result = handle_service_call(
            **self._call_kwargs(),
        )
        assert result.event_type == "TIMER"

    def test_event_type_sensor(self) -> None:
        """ServiceResult.event_type is SENSOR for sensor."""
        result = handle_service_call(
            **self._call_kwargs(
                sensor_value="60.0",
                trigger_entity="sensor.humidity",
            ),
        )
        assert result.event_type == "SENSOR"

    def test_event_type_switch(self) -> None:
        """ServiceResult.event_type is SWITCH when the
        trigger entity is a controlled entity."""
        result = handle_service_call(
            **self._call_kwargs(
                trigger_entity="switch.fan",
            ),
        )
        assert result.event_type == "SWITCH"

    def test_sensor_value_parsed(self) -> None:
        """ServiceResult.sensor_value is parsed float."""
        result = handle_service_call(
            **self._call_kwargs(
                sensor_value="65.3",
                trigger_entity="sensor.humidity",
            ),
        )
        assert result.sensor_value == 65.3

    def test_sensor_value_none_for_timer(self) -> None:
        """ServiceResult.sensor_value is None for timer."""
        result = handle_service_call(
            **self._call_kwargs(),
        )
        assert result.sensor_value is None

    def test_bootstrap_arms_auto_off_when_on(self) -> None:
        """Stranded-entity protection: state_data=None +
        any controlled entity on + auto_off_minutes>0 should
        arm ``auto_off_started_at`` so the device isn't
        stuck on indefinitely after HA restart."""
        result = handle_service_call(
            **self._call_kwargs(
                state_data=None,
                controlled_on_entities=[SW],
                auto_off_minutes=30,
                trigger_entity="sensor.humidity",
                sensor_value="55.0",
                current_time=T0,
            ),
        )
        assert result.state_dict["auto_off_started_at"] is not None
        # T0 is already on a minute boundary, so it stays at T0.
        assert result.state_dict["auto_off_started_at"] == T0.isoformat()

    def test_bootstrap_no_arm_when_off(self) -> None:
        """Set off at bootstrap -> no auto-off armed."""
        result = handle_service_call(
            **self._call_kwargs(
                state_data=None,
                controlled_on_entities=[],
                auto_off_minutes=30,
            ),
        )
        assert result.state_dict["auto_off_started_at"] is None

    def test_bootstrap_no_arm_when_auto_off_disabled(self) -> None:
        """auto_off_minutes=0 means user disabled auto-off
        entirely; the bootstrap-arm must respect that."""
        result = handle_service_call(
            **self._call_kwargs(
                state_data=None,
                controlled_on_entities=[SW],
                auto_off_minutes=0,
            ),
        )
        assert result.state_dict["auto_off_started_at"] is None

    def test_bootstrap_arm_then_timer_fires_at_timeout(
        self,
    ) -> None:
        """End-to-end: bootstrap-arm + later TIMER tick
        sees the armed timestamp and turns off when the
        timeout elapses."""
        r1 = handle_service_call(
            **self._call_kwargs(
                state_data=None,
                controlled_on_entities=[SW],
                auto_off_minutes=1,
                current_time=T0,
            ),
        )
        assert r1.state_dict["auto_off_started_at"] is not None

        r2 = handle_service_call(
            **self._call_kwargs(
                state_data=r1.state_dict,
                controlled_on_entities=[SW],
                auto_off_minutes=1,
                current_time=T0 + timedelta(minutes=1, seconds=1),
            ),
        )
        assert r2.action == Action.TURN_OFF

    def test_bootstrap_arm_uses_rounded_up_minute(self) -> None:
        """The bootstrap-arm formula rounds the call time
        UP to the next minute boundary so the actual auto-
        off delay is never SHORTER than the configured
        timeout.
        """
        non_boundary = T0 + timedelta(seconds=37)
        result = handle_service_call(
            **self._call_kwargs(
                state_data=None,
                controlled_on_entities=[SW],
                auto_off_minutes=30,
                trigger_entity="sensor.humidity",
                sensor_value="55.0",
                current_time=non_boundary,
            ),
        )
        expected = (T0 + timedelta(minutes=1)).isoformat()
        assert result.state_dict["auto_off_started_at"] == expected

    def test_handle_timer_arm_fallback_uses_tick_time(self) -> None:
        """The ``Controller._handle_timer`` arm-on-first-tick
        fallback arms the auto-off timer when a fresh
        ``state_data`` (``auto_off_started_at=None``) reaches
        the TIMER branch with the set on. The persisted arm
        timestamp matches the TIMER tick's
        ``_round_up_to_minute(current_time)``.
        """
        seed_state: dict[str, Any] = {
            "samples": [],
            "baseline": None,
            "overrides": [],
            "auto_off_started_at": None,
            "initialized": True,
        }
        # Tick at 12:00:42 -- rounded up should be 12:01:00.
        tick = T0 + timedelta(seconds=42)
        result = handle_service_call(
            **self._call_kwargs(
                state_data=seed_state,
                controlled_on_entities=[SW],
                auto_off_minutes=30,
                trigger_entity="timer",
                sensor_value="",
                current_time=tick,
            ),
        )
        expected = (T0 + timedelta(minutes=1)).isoformat()
        assert result.state_dict["auto_off_started_at"] == expected

    def test_malformed_blob_triggers_bootstrap_arm(self) -> None:
        """A blob that fails ``State.from_dict`` (e.g.
        partial-write upgrade leaves a stale shape) is
        treated like a missing blob: fresh ``State`` plus
        the stranded-entity arm."""
        bad_blob = {"samples": [{"value": "not-a-float"}]}
        result = handle_service_call(
            **self._call_kwargs(
                state_data=bad_blob,
                controlled_on_entities=[SW],
                auto_off_minutes=30,
                current_time=T0,
            ),
        )
        assert result.state_dict["auto_off_started_at"] is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", *sys.argv[1:]]))
