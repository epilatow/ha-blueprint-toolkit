# This is AI generated code
"""Business logic for sensor-threshold-based entity control.

Controls one or more entities based on sensor value spikes
(e.g., humidity), with manual override protection, auto-off,
and notifications.

Multi-entity aggregation: the controlled set is treated as a
single on/off unit. ``Inputs.controlled_on`` is True when ANY
controlled entity is on. A turn-ON targets the full configured
set; a turn-OFF targets only the subset that is currently on,
so the notification body and dispatched call name exactly the
entities the action affects.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any

from .. import helpers


class EventType(Enum):
    """Type of event that triggered evaluation."""

    SENSOR = auto()
    SWITCH = auto()
    TIMER = auto()


class Action(Enum):
    """Actions the automation can take."""

    NONE = auto()
    TURN_ON = auto()
    TURN_OFF = auto()


@dataclass
class Sample:
    """A single sensor reading with timestamp."""

    value: float
    timestamp: datetime


@dataclass
class Config:
    """Configuration parameters (set per-instance via blueprint)."""

    controlled_entities: list[str]
    trigger_threshold: float
    release_threshold: float
    sampling_window_seconds: int
    disable_window_seconds: int
    auto_off_minutes: int


@dataclass
class State:
    """Persistent state between invocations."""

    samples: list[Sample] = field(default_factory=list)
    baseline: float | None = None
    overrides: list[datetime] = field(default_factory=list)
    auto_off_started_at: datetime | None = None
    initialized: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON persistence."""
        return {
            "samples": [
                {
                    "value": s.value,
                    "timestamp": s.timestamp.isoformat(),
                }
                for s in self.samples
            ],
            "baseline": self.baseline,
            "overrides": [ts.isoformat() for ts in self.overrides],
            "auto_off_started_at": (
                self.auto_off_started_at.isoformat()
                if self.auto_off_started_at
                else None
            ),
            "initialized": self.initialized,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "State":
        """Deserialize State from JSON persistence.

        Contract: on a malformed input shape, raises
        ``KeyError`` (missing dict key), ``TypeError``
        (non-iterable / non-dict where one is expected),
        or ``ValueError`` (e.g. ``datetime.fromisoformat``
        on a malformed string). ``handle_service_call``
        catches exactly this set to fall back to a
        bootstrap-arm. Any future change here that broadens
        the raised set must update the matching except
        clause in ``handle_service_call``.
        """
        samples = [
            Sample(
                value=s["value"],
                timestamp=datetime.fromisoformat(s["timestamp"]),
            )
            for s in data.get("samples", [])
        ]
        overrides = [
            datetime.fromisoformat(ts) for ts in data.get("overrides", [])
        ]
        auto_off_raw = data.get("auto_off_started_at")
        return cls(
            samples=samples,
            baseline=data.get("baseline"),
            overrides=overrides,
            auto_off_started_at=(
                datetime.fromisoformat(auto_off_raw) if auto_off_raw else None
            ),
            initialized=data.get("initialized", False),
        )


@dataclass
class Inputs:
    """Inputs for a single evaluation."""

    current_time: datetime
    event_type: EventType
    sensor_value: float | None = None
    controlled_on_entities: list[str] = field(default_factory=list)
    friendly_names: dict[str, str] = field(default_factory=dict)

    @property
    def controlled_on(self) -> bool:
        """True iff any controlled entity is currently on."""
        return bool(self.controlled_on_entities)


@dataclass
class Result:
    """Result of a single evaluation.

    ``target_entities`` is the entity set the action applies
    to: the full configured list on a turn-ON, the on-subset
    on a turn-OFF. ``notification`` is non-empty when a
    notification should be sent.
    """

    action: Action = Action.NONE
    target_entities: list[str] = field(default_factory=list)
    reason: str = ""
    notification: str = ""


def parse_float(value: str | None) -> float | None:
    """Parse a string to float, handling HA special values."""
    if value is None:
        return None
    if value in ("", "unknown", "unavailable"):
        return None
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _round_up_to_minute(dt: datetime) -> datetime:
    """Round a datetime UP to the next minute boundary.

    auto_off_started_at is checked against time_pattern
    triggers that fire at minute boundaries.  Rounding up
    guarantees the actual auto-off delay is never shorter
    than the configured timeout (it may be up to ~1 minute
    longer).
    """
    if dt.second == 0 and dt.microsecond == 0:
        return dt
    return dt.replace(second=0, microsecond=0) + timedelta(
        minutes=1,
    )


def _maybe_arm_auto_off(
    state: "State",
    auto_off_minutes: int,
    current_time: datetime,
    controlled_on: bool,
) -> None:
    """Arm ``state.auto_off_started_at`` if conditions warrant.

    Idempotent. Used by every "first time this run we
    notice the controlled set is on without sensor
    management" path: bootstrap-arm, ``_handle_switch``
    startup-recovery, and ``_handle_timer`` arm-recovery.
    The "manual on" branch in ``_handle_switch`` does NOT
    use this -- it deliberately resets the clock on each
    manual transition.
    """
    if state.auto_off_started_at is not None:
        return
    if controlled_on and state.baseline is None and auto_off_minutes > 0:
        state.auto_off_started_at = _round_up_to_minute(current_time)


# -- Notification messages --
# Edit these templates to change user-facing text.
# {name} = controlled-entity friendly name(s).  Other
# placeholders are scenario-specific (documented inline).

# Entities turned on/off (shared across scenarios).
_MSG_SWITCH_ON = "Turned on {name}. {reason}"
_MSG_SWITCH_OFF = "Turned off {name}. {reason}"

# Sensor spike detected, turning entities on.
# {max_val}, {min_val}, {threshold}: sensor values.
_MSG_SPIKE_REASON = (
    "Sensor spike: {max_val} (max) > {min_val} (min) + {threshold} (threshold)"
)

# Sensor returned to normal, turning entities off.
# {max_val}, {baseline}, {release}: sensor values.
_MSG_RELEASE_REASON = (
    "Sensor release: {max_val} (max)"
    " <= {baseline} (baseline)"
    " + {release} (release)"
)

# Manual switch-off while sensor is overriding.
_MSG_OVERRIDE_ENABLE_REASON = "Manual off while sensor override active"

# Double switch-off disables sensor override.
_MSG_OVERRIDE_DISABLED = "Sensor override disabled for {name}"

# Auto-off timer expired.  {mins}: configured minutes.
_MSG_AUTO_OFF_REASON = "Auto-off after {mins} minute(s)"


def _friendly(
    entity_id: str,
    names: dict[str, str],
) -> str:
    """Look up friendly name, fallback to entity_id."""
    return names.get(entity_id, entity_id)


def _friendly_list(
    entity_ids: list[str],
    names: dict[str, str],
) -> str:
    """Comma-separated friendly names."""
    return ", ".join(_friendly(eid, names) for eid in entity_ids)


# -- Controller --


class Controller:
    """Stateful evaluator: holds the per-instance Config
    and dispatches each event (SENSOR / SWITCH / TIMER)
    to the matching handler. Per-call state and inputs
    are passed in; the controller never owns mutable
    state of its own."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def evaluate(
        self,
        state: State,
        inputs: Inputs,
    ) -> Result:
        """Dispatch to the correct event-type handler."""
        if inputs.event_type == EventType.SENSOR:
            return self._handle_sensor(state, inputs)
        if inputs.event_type == EventType.SWITCH:
            return self._handle_switch(state, inputs)
        if inputs.event_type == EventType.TIMER:
            return self._handle_timer(state, inputs)
        return Result()

    def _handle_sensor(
        self,
        state: State,
        inputs: Inputs,
    ) -> Result:
        """Handle sensor value change event."""
        if inputs.sensor_value is None:
            return Result()

        value = inputs.sensor_value
        now = inputs.current_time
        window = timedelta(
            seconds=self.config.sampling_window_seconds,
        )

        # Prune old samples and add new one
        state.samples = [
            s for s in state.samples if now - s.timestamp <= window
        ]
        state.samples.append(Sample(value=value, timestamp=now))

        # Compute min/max over window
        values = [s.value for s in state.samples]
        min_val = min(values)
        max_val = max(values)

        if state.baseline is None:
            return self._check_spike(state, inputs, min_val, max_val)

        return self._check_release(state, inputs, max_val)

    def _check_spike(
        self,
        state: State,
        inputs: Inputs,
        min_val: float,
        max_val: float,
    ) -> Result:
        """Check if sensor values spiked above threshold."""
        threshold = self.config.trigger_threshold
        if max_val <= min_val + threshold:
            return Result()

        # Spike detected: set baseline
        state.baseline = min_val
        state.overrides = []
        state.auto_off_started_at = None

        if inputs.controlled_on:
            # Already on (e.g., manual), sensor takes over
            return Result()

        name = _friendly_list(
            self.config.controlled_entities,
            inputs.friendly_names,
        )
        reason = _MSG_SPIKE_REASON.format(
            max_val=max_val,
            min_val=min_val,
            threshold=threshold,
        )
        return Result(
            action=Action.TURN_ON,
            target_entities=list(self.config.controlled_entities),
            reason=reason,
            notification=_MSG_SWITCH_ON.format(
                name=name,
                reason=reason,
            ),
        )

    def _check_release(
        self,
        state: State,
        inputs: Inputs,
        max_val: float,
    ) -> Result:
        """Check if sensor values dropped below release."""
        assert state.baseline is not None
        release = self.config.release_threshold

        if max_val > state.baseline + release:
            return Result()

        # Release detected: clear baseline
        old_baseline = state.baseline
        state.baseline = None
        state.overrides = []
        state.auto_off_started_at = None

        if not inputs.controlled_on:
            # Already off
            return Result()

        # Turn off only the subset currently on; listing
        # entities already off would misreport the action.
        on_subset = list(inputs.controlled_on_entities)
        name = _friendly_list(on_subset, inputs.friendly_names)
        reason = _MSG_RELEASE_REASON.format(
            max_val=max_val,
            baseline=old_baseline,
            release=release,
        )
        return Result(
            action=Action.TURN_OFF,
            target_entities=on_subset,
            reason=reason,
            notification=_MSG_SWITCH_OFF.format(
                name=name,
                reason=reason,
            ),
        )

    def _handle_switch(
        self,
        state: State,
        inputs: Inputs,
    ) -> Result:
        """Handle controlled-entity state change event."""
        controlled_on = inputs.controlled_on

        # Startup recovery
        if not state.initialized:
            state.initialized = True
            _maybe_arm_auto_off(
                state,
                self.config.auto_off_minutes,
                inputs.current_time,
                controlled_on,
            )
            return Result()

        if controlled_on:
            if state.baseline is None:
                # Manual on: schedule auto-off
                if self.config.auto_off_minutes > 0:
                    state.auto_off_started_at = _round_up_to_minute(
                        inputs.current_time,
                    )
            else:
                # Sensor managing: cancel auto-off
                state.auto_off_started_at = None
            return Result()

        # All controlled entities off
        if state.baseline is not None:
            return self._handle_manual_override(state, inputs)

        # Off without baseline: cancel auto-off
        state.auto_off_started_at = None
        return Result()

    def _handle_manual_override(
        self,
        state: State,
        inputs: Inputs,
    ) -> Result:
        """Handle manual switch-off while baseline active."""
        now = inputs.current_time
        window_s = self.config.disable_window_seconds

        # Filter overrides by disable window
        if window_s > 0:
            window = timedelta(seconds=window_s)
            state.overrides = [
                ts for ts in state.overrides if now - ts <= window
            ]
        else:
            state.overrides = []

        state.overrides.append(now)

        should_disable = window_s > 0 and len(state.overrides) >= 2

        if should_disable:
            # Double-off: disable sensor override
            state.baseline = None
            state.overrides = []
            state.auto_off_started_at = None
            name = _friendly_list(
                self.config.controlled_entities,
                inputs.friendly_names,
            )
            return Result(
                notification=_MSG_OVERRIDE_DISABLED.format(
                    name=name,
                ),
            )

        # Re-enable: turn the full controlled set back on.
        name = _friendly_list(
            self.config.controlled_entities,
            inputs.friendly_names,
        )
        reason = _MSG_OVERRIDE_ENABLE_REASON
        return Result(
            action=Action.TURN_ON,
            target_entities=list(self.config.controlled_entities),
            reason=reason,
            notification=_MSG_SWITCH_ON.format(
                name=name,
                reason=reason,
            ),
        )

    def _handle_timer(
        self,
        state: State,
        inputs: Inputs,
    ) -> Result:
        """Handle periodic timer event for auto-off."""
        # Start auto-off if controlled set is on with no
        # baseline and no timer running. The bootstrap-arm
        # in ``handle_service_call`` covers the most common
        # post-restart case (first event after lost state);
        # this branch covers the rest -- e.g. a SWITCH event
        # was missed because the user toggled an entity via
        # a different integration that didn't fire a
        # state-change trigger.
        _maybe_arm_auto_off(
            state,
            self.config.auto_off_minutes,
            inputs.current_time,
            inputs.controlled_on,
        )

        if (
            state.auto_off_started_at is not None
            and state.baseline is None
            and inputs.controlled_on
            and self.config.auto_off_minutes > 0
        ):
            elapsed = (
                inputs.current_time - state.auto_off_started_at
            ).total_seconds()
            timeout = self.config.auto_off_minutes * 60
            if elapsed >= timeout:
                state.auto_off_started_at = None
                # Turn off only the subset currently on.
                on_subset = list(inputs.controlled_on_entities)
                name = _friendly_list(on_subset, inputs.friendly_names)
                mins = self.config.auto_off_minutes
                reason = _MSG_AUTO_OFF_REASON.format(
                    mins=f"{mins:g}",
                )
                return Result(
                    action=Action.TURN_OFF,
                    target_entities=on_subset,
                    reason=reason,
                    notification=_MSG_SWITCH_OFF.format(
                        name=name,
                        reason=reason,
                    ),
                )

        return Result()


def determine_event_type(
    trigger_entity: str,
    controlled_entities: list[str],
) -> EventType:
    """Determine event type from trigger entity.

    A controlled entity changing state is a SWITCH event;
    the ``"timer"`` / empty / ``none`` sentinels are TIMER;
    anything else is a SENSOR reading.
    """
    if trigger_entity in controlled_entities:
        return EventType.SWITCH
    if trigger_entity in ("", "timer", "None", "none"):
        return EventType.TIMER
    return EventType.SENSOR


def evaluate(
    *,
    current_time: datetime,
    state: State,
    controlled_entities: list[str],
    controlled_on_entities: list[str],
    friendly_names: dict[str, str],
    sensor_value: str,
    trigger_entity: str,
    trigger_threshold: float,
    release_threshold: float,
    sampling_window_seconds: int,
    disable_window_seconds: int,
    auto_off_minutes: int,
    notification_prefix: str,
    notification_suffix: str,
) -> Result:
    """Top-level evaluation entrypoint.

    Builds Config, determines event type, parses sensor
    value, evaluates via Controller, and formats the
    notification.  Returns a fully-formed Result.
    """
    config = Config(
        controlled_entities=controlled_entities,
        trigger_threshold=trigger_threshold,
        release_threshold=release_threshold,
        sampling_window_seconds=sampling_window_seconds,
        disable_window_seconds=disable_window_seconds,
        auto_off_minutes=auto_off_minutes,
    )

    event_type = determine_event_type(
        trigger_entity,
        controlled_entities,
    )

    parsed_value: float | None = None
    if event_type == EventType.SENSOR:
        parsed_value = parse_float(sensor_value)

    inputs = Inputs(
        current_time=current_time,
        event_type=event_type,
        sensor_value=parsed_value,
        controlled_on_entities=controlled_on_entities,
        friendly_names=friendly_names,
    )

    result = Controller(config).evaluate(state, inputs)

    if result.notification:
        result.notification = helpers.format_notification(
            result.notification,
            notification_prefix,
            notification_suffix,
            current_time,
        )

    return result


@dataclass
class ServiceResult:
    """Outcome of handle_service_call for the bridge to act on."""

    state_dict: dict[str, Any]
    action: Action = Action.NONE
    target_entities: list[str] = field(default_factory=list)
    reason: str = ""
    event_type: str = ""
    sensor_value: float | None = None
    notification: str = ""


def handle_service_call(
    *,
    state_data: dict[str, Any] | None,
    current_time: datetime,
    controlled_entities: list[str],
    controlled_on_entities: list[str],
    **kwargs: Any,
) -> ServiceResult:
    """Bridge entry point called by the handler.

    Accepts pre-loaded data (no HA dependencies) and
    returns a ``ServiceResult`` describing what the caller
    should do.  The caller handles all HA interactions:
    state persistence, service calls, and notifications.

    The evaluation flow:
    1. Parse state from persisted JSON
    2. Determine event type (SENSOR, SWITCH, or TIMER)
    3. Parse sensor value (for SENSOR events)
    4. Evaluate via Controller:
       - SENSOR: track min/max in rolling window,
         detect spike (turn on) or release (turn off)
       - SWITCH: handle manual on (start auto-off),
         manual off (re-activate or double-off disable)
       - TIMER: check auto-off expiry
    5. Format notification with prefix/suffix

    Purely reactive: no sleeping, no waiting.  Auto-off
    records a start timestamp rounded up to the next
    minute boundary; the integration's minute-tick
    timer fires every minute to check expiry.

    Stranded-entity protection: when the persisted state
    blob is missing or malformed (HA restart, fresh
    setup, partial-write upgrade), bootstrap a fresh
    ``State`` AND -- if any controlled entity is currently
    on with auto-off enabled -- arm ``auto_off_started_at``
    so the device isn't stuck on indefinitely waiting
    for an event that re-arms the timer. The TIMER
    branch of ``Controller._handle_timer`` would catch
    this on the next minute-tick anyway, but doing it
    explicitly at bootstrap is clearer and recovers up
    to one tick faster (and covers the SENSOR-first
    post-restart case where no TIMER fires until the
    periodic timer arms).

    Remaining kwargs are passed through to evaluate().
    """
    # Parse state. Track whether we ended up with a
    # bootstrapped (empty) State so the stranded-entity
    # arm below knows to fire.
    bootstrapped = False
    if state_data is None:
        s = State()
        bootstrapped = True
    else:
        try:
            s = State.from_dict(state_data)
        except (KeyError, TypeError, ValueError):
            # Malformed blob from a prior version -- treat
            # as missing and rebuild from scratch.
            s = State()
            bootstrapped = True

    if bootstrapped:
        auto_off_min: int = int(kwargs.get("auto_off_minutes", 0))
        # Bootstrap state: ``s.baseline`` is None and
        # ``s.auto_off_started_at`` is None by default, so
        # the helper's guards reduce to "any controlled
        # entity on + minutes > 0".
        _maybe_arm_auto_off(
            s,
            auto_off_min,
            current_time,
            bool(controlled_on_entities),
        )
        # Mark initialized so a subsequent SWITCH event
        # doesn't re-run ``_handle_switch``'s startup-
        # recovery branch (which would idempotently re-arm
        # ``auto_off_started_at`` to the same value but
        # muddies the contract -- after the bootstrap-arm,
        # state is "initialized for this run").
        s.initialized = True

    # Determine event type and parse sensor value
    event_type = determine_event_type(
        kwargs.get("trigger_entity", "timer"),
        controlled_entities,
    )
    parsed_sensor: float | None = None
    if event_type == EventType.SENSOR:
        parsed_sensor = parse_float(
            kwargs.get("sensor_value", ""),
        )

    # Evaluate
    result = evaluate(
        current_time=current_time,
        state=s,
        controlled_entities=controlled_entities,
        controlled_on_entities=controlled_on_entities,
        **kwargs,
    )

    return ServiceResult(
        state_dict=s.to_dict(),
        action=result.action,
        target_entities=result.target_entities,
        reason=result.reason,
        event_type=event_type.name,
        sensor_value=parsed_sensor,
        notification=result.notification or "",
    )
