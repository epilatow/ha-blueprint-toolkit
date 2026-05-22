# This is AI generated code
"""HA wiring for sensor_threshold_entity_controller.

STEC-specific shape on top of the standard three-layer
dispatch (see ``DEVELOPMENT.md`` for the universal
pattern):

- Three input event types: SENSOR (sensor entity state
  change), SWITCH (controlled-entity state change), TIMER
  (periodic minute tick). Reactive triggers stay in
  the blueprint (a state-change trigger per watched
  entity); the periodic tick is integration-owned via
  ``helpers.schedule_periodic_with_jitter``.
- Per-instance state (sample window, baseline,
  override list, auto_off_started_at) lives in the
  diagnostic state entity's ``data`` attribute as a
  JSON blob. Volatile across HA restarts; the periodic
  + reactive triggers re-bootstrap state on the next
  invocation, and ``handle_service_call`` arms auto-off
  at bootstrap if any controlled entity is currently on.
- Action: a single ``homeassistant.turn_on`` /
  ``homeassistant.turn_off`` against the result's
  ``target_entities`` set (the full configured list on a
  turn-ON, the on-subset on a turn-OFF), with the
  caller's ``context`` propagated so logbook attribution
  is correct.
- Notification dispatch is owned by the blueprint, not
  the handler. The service registers with
  ``SupportsResponse.OPTIONAL`` and returns a
  ``ServiceResponse`` mapping carrying the pre-built
  notification body under ``notification_message`` --
  the blueprint captures it via ``response_variable``
  and runs the user-configured ``notify_action`` step.
  No-op evaluations return an empty / absent message
  so the blueprint's ``choose`` short-circuits. State
  saving runs BEFORE the handler returns, so a notify-
  action failure inside the blueprint runner can't
  lose state.
- Single notification slot for argparse / config
  errors via the shared
  ``helpers.make_config_error_notification`` /
  ``emit_config_error`` path. STEC has no per-event
  persistent-notification stream of its own; the
  per-instance sweep dismisses stale config-error
  entries on every successful run.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..helpers import (
    BlueprintHandlerSpec,
    TypedServiceResponse,
    automation_friendly_name,
    entity_friendly_names,
    entry_for_domain,
    filter_on_entities,
    instance_state_entity_id,
    make_emit_config_error,
    make_lifecycle_mutators,
    make_periodic_trigger_callback,
    process_persistent_notifications_with_sweep,
    register_blueprint_handler,
    schedule_periodic_with_jitter,
    spec_bucket,
    unregister_blueprint_handler,
    update_instance_state,
    validate_controlled_entity_domains,
    validate_payload_or_emit_config_error,
)

# STEC takes a user-supplied ``notification_prefix`` string
# (the per-instance body prefix, e.g. ``"STEC: "``) as a
# blueprint input. Alias the helper that builds the per-
# instance notification-ID prefix so the two don't collide
# inside the service layer.
from ..helpers import notification_prefix as _notification_id_prefix
from . import logic

_LOGGER = logging.getLogger(__name__)

_SERVICE = "sensor_threshold_entity_controller"
_SERVICE_TAG = "STEC"
_SERVICE_NAME = "Sensor Threshold Entity Controller"
BLUEPRINT_PATH = "blueprint_toolkit/sensor_threshold_entity_controller.yaml"

# The integration-owned periodic tick fires every minute.
# Hardcoded rather than a blueprint input -- the cadence
# is load-bearing for the spike-detection sample window
# and isn't user-tunable today.
_PERIODIC_INTERVAL = timedelta(minutes=1)

# ``trigger_entity`` value the integration-owned periodic
# callback passes to mark a tick as "timer" (the third
# event type alongside SENSOR + SWITCH). The logic
# module's ``determine_event_type`` recognises
# ``"timer"`` as the canonical sentinel.
_TIMER_TRIGGER_ENTITY = "timer"


# --------------------------------------------------------
# Per-instance in-memory state
# --------------------------------------------------------


@dataclass
class StecInstanceState:
    """In-memory state for one STEC automation instance.

    Lost on HA restart; the periodic timer + the
    blueprint's reactive triggers re-bootstrap the
    persistent state from the diagnostic entity's
    ``data`` attribute on the next invocation.
    """

    instance_id: str
    cancel_timer: Callable[[], None] | None = field(default=None, repr=False)


# --------------------------------------------------------
# Service-call schema
# --------------------------------------------------------

_SCHEMA = vol.Schema(
    {
        vol.Required("instance_id"): cv.entity_id,
        vol.Required("trigger_id"): vol.Coerce(str),
        vol.Required("controlled_entities_raw"): vol.All(
            cv.ensure_list, [cv.entity_id]
        ),
        vol.Required("sensor_value"): vol.Coerce(str),
        vol.Required("trigger_entity"): vol.Coerce(str),
        vol.Required("trigger_threshold_raw"): vol.Coerce(float),
        vol.Required("release_threshold_raw"): vol.Coerce(float),
        vol.Required("sampling_window_seconds_raw"): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=3600)
        ),
        vol.Required("disable_window_seconds_raw"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=60)
        ),
        vol.Required("auto_off_minutes_raw"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=1440)
        ),
        vol.Required("notification_prefix"): vol.Coerce(str),
        vol.Required("notification_suffix"): vol.Coerce(str),
        vol.Required("debug_logging_raw"): cv.boolean,
    },
    extra=vol.ALLOW_EXTRA,
)


# --------------------------------------------------------
# Per-instance state accessor
# --------------------------------------------------------


def _instances(hass: HomeAssistant) -> dict[str, StecInstanceState]:
    """Per-instance state map under our service's bucket."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {}
    bucket = spec_bucket(entries[0], _SERVICE)
    instances: dict[str, StecInstanceState] = bucket.setdefault("instances", {})
    return instances


# --------------------------------------------------------
# Layer 1: entrypoint
# --------------------------------------------------------


async def _async_entrypoint(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ServiceResponse:
    """Service handler -- thin wrapper, hands off to argparse.

    The internal layers return a typed ``TypedServiceResponse``
    dataclass; this entrypoint is the single place we
    convert to HA's wire-format ``ServiceResponse`` dict
    via ``dataclasses.asdict``. Keeping the conversion
    here means every other return site stays nominally
    typed and mypy rejects bare-dict returns.
    """
    return asdict(await _async_argparse(hass, call, now=dt_util.now()))


# --------------------------------------------------------
# Layer 2: argparse
# --------------------------------------------------------


_emit_config_error = make_emit_config_error(
    service=_SERVICE,
    service_tag=_SERVICE_TAG,
)


async def _async_argparse(
    hass: HomeAssistant,
    call: ServiceCall,
    *,
    now: datetime,
) -> TypedServiceResponse:
    """Validate, build context, dispatch to the service layer."""
    raw = dict(call.data)

    data = await validate_payload_or_emit_config_error(
        hass,
        raw,
        _SCHEMA,
        _emit_config_error,
    )
    if data is None:
        return TypedServiceResponse()

    instance_id: str = data["instance_id"]
    errors: list[str] = []

    # Cross-field: the controlled set must be non-empty,
    # every entity must exist as a state in HA today, and
    # each must live in a domain that responds to
    # ``homeassistant.turn_on`` / ``turn_off``. Catches
    # typos AND selector-bypassing YAML edits before the
    # service layer dispatches a silent no-op against an
    # unsupported entity.
    controlled_entities: list[str] = list(data["controlled_entities_raw"])
    if not controlled_entities:
        errors.append(
            "controlled_entities: at least one entity is required",
        )
    for eid in controlled_entities:
        if hass.states.get(eid) is None:
            errors.append(
                f"controlled_entities: {eid!r} is not a known entity",
            )
    errors.extend(
        validate_controlled_entity_domains(
            sorted(controlled_entities),
            "controlled_entities",
        ),
    )

    # Argparse complete; emit accumulated errors (or
    # dismiss any prior config_error notification).
    await _emit_config_error(hass, instance_id, errors)
    if errors:
        return TypedServiceResponse()

    return await _async_service_layer(
        hass,
        call,
        now=now,
        instance_id=instance_id,
        trigger_id=data["trigger_id"],
        controlled_entities=controlled_entities,
        sensor_value=data["sensor_value"],
        trigger_entity=data["trigger_entity"],
        trigger_threshold=data["trigger_threshold_raw"],
        release_threshold=data["release_threshold_raw"],
        sampling_window_seconds=data["sampling_window_seconds_raw"],
        disable_window_seconds=data["disable_window_seconds_raw"],
        auto_off_minutes=data["auto_off_minutes_raw"],
        notification_prefix=data["notification_prefix"],
        notification_suffix=data["notification_suffix"],
        debug_logging=data["debug_logging_raw"],
    )


# --------------------------------------------------------
# Layer 3: service layer
# --------------------------------------------------------


async def _async_service_layer(
    hass: HomeAssistant,
    call: ServiceCall,
    *,
    now: datetime,
    instance_id: str,
    trigger_id: str,
    controlled_entities: list[str],
    sensor_value: str,
    trigger_entity: str,
    trigger_threshold: float,
    release_threshold: float,
    sampling_window_seconds: int,
    disable_window_seconds: int,
    auto_off_minutes: int,
    notification_prefix: str,
    notification_suffix: str,
    debug_logging: bool,
) -> TypedServiceResponse:
    """Run the controller, apply actions, return notify message.

    Returns a ``ServiceResponse`` mapping the blueprint
    runner captures via ``response_variable``. The
    ``notification_message`` slot carries the pre-built
    body when the controller decided to notify (empty
    string otherwise); the blueprint then runs the
    user-supplied ``notify_action`` step against it.
    """
    state = _instances(hass).setdefault(
        instance_id,
        StecInstanceState(instance_id=instance_id),
    )

    # Make sure the periodic timer is armed (idempotent;
    # arms once per instance and stays until teardown).
    entry = entry_for_domain(hass)
    if entry is not None:
        _ensure_timer(hass, entry, state)

    notif_prefix = _notification_id_prefix(_SERVICE, instance_id)
    tag = f"[{_SERVICE_TAG}: {automation_friendly_name(hass, instance_id)}]"

    # Load the persistent state blob from the diagnostic
    # state entity's ``data`` attribute. Empty / missing
    # is fine -- the logic module bootstraps fresh state.
    state_data = _load_state_blob(hass, instance_id)

    # Read the live controlled-entity states: the on-subset
    # (order-preserving, so a turn-OFF body lists entities
    # in the user's configured order) and friendly names
    # for the notification body.
    controlled_on_entities = filter_on_entities(hass, controlled_entities)
    friendly_names = entity_friendly_names(hass, controlled_entities)

    # Pure-function controller call -- no HA dependencies.
    result = logic.handle_service_call(
        state_data=state_data,
        current_time=now,
        controlled_entities=controlled_entities,
        controlled_on_entities=controlled_on_entities,
        friendly_names=friendly_names,
        sensor_value=sensor_value,
        trigger_entity=trigger_entity,
        trigger_threshold=trigger_threshold,
        release_threshold=release_threshold,
        sampling_window_seconds=sampling_window_seconds,
        disable_window_seconds=disable_window_seconds,
        auto_off_minutes=auto_off_minutes,
        notification_prefix=notification_prefix,
        notification_suffix=notification_suffix,
    )

    # STEC has no persistent-finding stream of its own; the
    # sweep just cleans up stale config-error notifications
    # left over from a prior bad config.
    await process_persistent_notifications_with_sweep(
        hass,
        [],
        sweep_prefix=notif_prefix,
    )

    # State save runs before the response is returned so a
    # downstream notify-action failure inside the blueprint
    # runner cannot lose the controller state.
    update_instance_state(
        hass,
        service_tag=_SERVICE_TAG,
        instance_id=instance_id,
        last_run=now,
        runtime=(dt_util.now() - now).total_seconds(),
        state=result.action.name,
        extra_attributes={
            "last_trigger": trigger_id or "",
            "last_event": result.event_type,
            "last_action": result.action.name,
            "last_reason": result.reason or "n/a",
            "last_sensor": (
                str(result.sensor_value)
                if result.sensor_value is not None
                else "n/a"
            ),
            "controlled_entities": controlled_entities,
            "controlled_on": bool(controlled_on_entities),
            # JSON-encoded controller state for the next
            # tick's load. Volatile across HA restarts
            # (state machine is cleared); the next periodic
            # tick re-bootstraps from empty.
            "data": json.dumps(result.state_dict),
        },
    )

    # Single ``homeassistant.turn_on`` / ``turn_off`` against
    # the result's ``target_entities`` (full configured set
    # on a turn-ON, the on-subset on a turn-OFF).
    # ``call.context`` propagates so the logbook attributes
    # the action to the user who triggered the automation,
    # not to the integration.
    if result.action == logic.Action.TURN_ON and result.target_entities:
        await hass.services.async_call(
            "homeassistant",
            "turn_on",
            {"entity_id": result.target_entities},
            context=call.context,
            blocking=False,
        )
    elif result.action == logic.Action.TURN_OFF and result.target_entities:
        await hass.services.async_call(
            "homeassistant",
            "turn_off",
            {"entity_id": result.target_entities},
            context=call.context,
            blocking=False,
        )

    if debug_logging:
        _LOGGER.warning(
            "%s event=%s controlled_on=%s baseline=%s"
            " auto_off=%s samples=%s -> %s %r",
            tag,
            result.event_type,
            bool(controlled_on_entities),
            result.state_dict.get("baseline"),
            result.state_dict.get("auto_off_started_at"),
            len(result.state_dict.get("samples", [])),
            result.action.name,
            result.reason,
        )

    return TypedServiceResponse(
        notification_message=result.notification or "",
    )


# --------------------------------------------------------
# State-blob load helper
# --------------------------------------------------------


def _load_state_blob(
    hass: HomeAssistant,
    instance_id: str,
) -> dict[str, Any] | None:
    """Read the JSON state blob from the diagnostic entity.

    Returns the parsed dict or ``None`` if the entity
    doesn't exist, has no ``data`` attribute, or the
    JSON is malformed. Any of those conditions means
    "no prior state" -- the logic module bootstraps
    fresh.
    """
    state_eid = instance_state_entity_id(_SERVICE_TAG, instance_id)
    st = hass.states.get(state_eid)
    if st is None:
        return None
    raw = st.attributes.get("data", "")
    if not raw:
        return None
    if not isinstance(raw, str):
        # Contract: ``data`` is the JSON blob the prior run
        # wrote via ``_save_state``, which stores a string.
        # If something else (an int, dict, etc.) is sitting
        # there, treat the slot as missing and let the
        # bootstrap path rebuild fresh state.
        return None
    try:
        loaded: dict[str, Any] = json.loads(raw)
    except ValueError:
        # Malformed blob -- treat as missing. Next save
        # will rewrite it cleanly.
        return None
    return loaded


# --------------------------------------------------------
# Periodic timer + recovery kick
# --------------------------------------------------------


def _ensure_timer(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: StecInstanceState,
) -> None:
    """Arm the periodic minute-tick timer if not yet armed.

    The interval is fixed (``_PERIODIC_INTERVAL`` = 1
    minute); no blueprint input controls it, so re-arming
    on interval change is moot. First call arms; subsequent
    calls within the same instance lifetime are no-ops.
    """
    if state.cancel_timer is not None:
        return
    state.cancel_timer = schedule_periodic_with_jitter(
        hass,
        entry,
        interval=_PERIODIC_INTERVAL,
        instance_id=state.instance_id,
        action=make_periodic_trigger_callback(
            hass,
            state.instance_id,
            instances_getter=_instances,
            service_tag=_SERVICE_TAG,
            logger=_LOGGER,
            extra_variables={"trigger_entity": _TIMER_TRIGGER_ENTITY},
        ),
    )


# --------------------------------------------------------
# Lifecycle mutators
# --------------------------------------------------------


_MUTATORS = make_lifecycle_mutators(
    instances_getter=_instances,
    cancel_field="cancel_timer",
    service_tag=_SERVICE_TAG,
    logger=_LOGGER,
)
_on_reload = _MUTATORS.on_reload
_on_entity_remove = _MUTATORS.on_entity_remove
_on_entity_rename = _MUTATORS.on_entity_rename
_on_teardown = _MUTATORS.on_teardown


# --------------------------------------------------------
# Spec + register / unregister
# --------------------------------------------------------


_SPEC = BlueprintHandlerSpec(
    service=_SERVICE,
    service_tag=_SERVICE_TAG,
    service_name=_SERVICE_NAME,
    blueprint_path=BLUEPRINT_PATH,
    service_handler=_async_entrypoint,
    # The handler returns a ``ServiceResponse`` mapping the
    # blueprint runner captures via ``response_variable``;
    # ``OPTIONAL`` lets non-blueprint callers (manual
    # tests, the integration's own kicks) ignore the
    # response without an error.
    supports_response=SupportsResponse.OPTIONAL,
    # The blueprint's reactive triggers don't carry
    # ``trigger_id`` / ``trigger_entity`` defaults; the
    # synthetic kick supplies sensible fallbacks so the
    # controller's event-type determination has the
    # "timer" sentinel.
    kick_variables={
        "trigger_id": "manual",
        "trigger_entity": _TIMER_TRIGGER_ENTITY,
    },
    on_reload=_on_reload,
    on_entity_remove=_on_entity_remove,
    on_entity_rename=_on_entity_rename,
    on_teardown=_on_teardown,
)


async def async_register(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Register STEC's service + lifecycle via the shared helper."""
    await register_blueprint_handler(hass, entry, _SPEC)


async def async_unregister(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Tear down STEC's service + lifecycle via the shared helper."""
    await unregister_blueprint_handler(hass, entry, _SPEC)


__all__ = [
    "BLUEPRINT_PATH",
    "StecInstanceState",
    "async_register",
    "async_unregister",
]
