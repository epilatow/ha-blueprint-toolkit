# This is AI generated code
"""HA wiring for battery_watchdog.

BW-specific shape on top of the standard three-layer
dispatch (see ``AUTOMATIONS.md`` for the universal
pattern):

- Periodic scan via integration-owned scheduling
  (``helpers.schedule_periodic_with_jitter``).
- The battery inputs -- every ``sensor`` / ``binary_sensor``
  state whose ``device_class`` is ``battery``, with its
  registry entry's integration, device, and area -- are
  read on the event loop, since the state machine and
  registries are loop-only. The scan itself is cheap, so
  ``logic.run_evaluation`` runs inline.
- One finding notification per instance (the low-battery
  list) plus the unmatched-directives slot, sweep-dispatched
  together so nothing a prior scan published lingers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import probatio
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..helpers import (
    BlueprintHandlerSpec,
    JoinedRegexLine,
    automation_friendly_name,
    cv_ha_domain_list,
    entity_area_name,
    entry_for_domain,
    make_emit_config_error,
    make_lifecycle_mutators,
    make_periodic_trigger_callback,
    make_unmatched_directives_notification,
    notification_prefix,
    process_persistent_notifications_with_sweep,
    register_blueprint_handler,
    schedule_periodic_with_jitter,
    spec_bucket,
    unregister_blueprint_handler,
    update_instance_state,
    validate_and_join_regex_patterns,
    validate_payload_or_emit_config_error,
)
from . import logic

_LOGGER = logging.getLogger(__name__)

_SERVICE = "battery_watchdog"
_SERVICE_TAG = "BW"
_SERVICE_NAME = "Battery Watchdog"
BLUEPRINT_PATH = "blueprint_toolkit/battery_watchdog.yaml"

# The state domains a battery reading comes from.
_BATTERY_DOMAINS = ("sensor", "binary_sensor")


# --------------------------------------------------------
# Per-instance in-memory state
# --------------------------------------------------------


@dataclass
class BwInstanceState:
    """In-memory state for one BW automation instance.

    Lost on HA restart; the periodic timer + restart-
    recovery kick re-arm everything on the next tick.
    """

    instance_id: str
    # The interval the timer was last armed with, so a
    # blueprint-input change re-arms it.
    armed_interval_minutes: int = 0
    cancel_timer: Callable[[], None] | None = field(default=None, repr=False)


# --------------------------------------------------------
# Service-call schema
# --------------------------------------------------------

_SCHEMA = probatio.Schema(
    {
        probatio.Required("instance_id"): cv.entity_id,
        probatio.Required("trigger_id"): probatio.Coerce(str),
        probatio.Required("battery_warning_level_raw"): probatio.All(
            probatio.Coerce(int), probatio.Range(min=0, max=100)
        ),
        probatio.Required("include_integrations_raw"): cv_ha_domain_list,
        probatio.Required("exclude_integrations_raw"): cv_ha_domain_list,
        probatio.Required("exclude_device_name_regex_raw"): probatio.Coerce(
            str
        ),
        probatio.Required("include_entities_raw"): cv.entity_ids,
        probatio.Required("exclude_entities_raw"): cv.entity_ids,
        probatio.Required("exclude_entity_id_regex_raw"): probatio.Coerce(str),
        probatio.Required("exclude_entity_name_regex_raw"): probatio.Coerce(
            str
        ),
        probatio.Required("check_interval_minutes_raw"): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=10080)
        ),
        probatio.Required("validate_includes_excludes_raw"): cv.boolean,
        probatio.Required("debug_logging_raw"): cv.boolean,
    },
    extra=probatio.ALLOW_EXTRA,
)


# --------------------------------------------------------
# Per-instance state accessor
# --------------------------------------------------------


def _instances(hass: HomeAssistant) -> dict[str, BwInstanceState]:
    """Per-instance state map under our service's bucket."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {}
    bucket = spec_bucket(entries[0], _SERVICE)
    instances: dict[str, BwInstanceState] = bucket.setdefault("instances", {})
    return instances


# --------------------------------------------------------
# Layer 1: entrypoint
# --------------------------------------------------------


async def _async_entrypoint(hass: HomeAssistant, call: ServiceCall) -> None:
    """Service handler -- thin wrapper, hands off to argparse."""
    await _async_argparse(hass, call, now=dt_util.now())


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
) -> None:
    """Validate, build context, dispatch to the service layer."""
    raw = dict(call.data)

    data = await validate_payload_or_emit_config_error(
        hass,
        raw,
        _SCHEMA,
        _emit_config_error,
    )
    if data is None:
        return

    instance_id: str = data["instance_id"]
    errors: list[str] = []

    dev_regex = validate_and_join_regex_patterns(
        data["exclude_device_name_regex_raw"],
        "exclude_device_name_regex",
    )
    errors.extend(dev_regex.errors)
    eid_regex = validate_and_join_regex_patterns(
        data["exclude_entity_id_regex_raw"],
        "exclude_entity_id_regex",
    )
    errors.extend(eid_regex.errors)
    name_regex = validate_and_join_regex_patterns(
        data["exclude_entity_name_regex_raw"],
        "exclude_entity_name_regex",
    )
    errors.extend(name_regex.errors)

    include_entities: list[str] = list(data["include_entities_raw"])
    if include_entities:
        conflicts = [
            name
            for name, value in (
                ("include_integrations", data["include_integrations_raw"]),
                ("exclude_integrations", data["exclude_integrations_raw"]),
                ("exclude_device_name_regex", dev_regex.lines),
                ("exclude_entities", data["exclude_entities_raw"]),
                ("exclude_entity_id_regex", eid_regex.lines),
                ("exclude_entity_name_regex", name_regex.lines),
            )
            if value
        ]
        if conflicts:
            errors.append(
                "include_entities lists the exact batteries to watch, so"
                " it can't be combined with other include / exclude"
                " inputs. Clear include_entities, or clear: "
                f"{', '.join(conflicts)}."
            )

    await _emit_config_error(hass, instance_id, errors)
    if errors:
        return

    await _async_service_layer(
        hass,
        call,
        now=now,
        instance_id=instance_id,
        trigger_id=data["trigger_id"],
        warning_level=data["battery_warning_level_raw"],
        include_integrations=list(data["include_integrations_raw"]),
        exclude_integrations=list(data["exclude_integrations_raw"]),
        exclude_device_name_regex=dev_regex.joined,
        exclude_device_name_regex_lines=dev_regex.lines,
        include_entities=include_entities,
        exclude_entities=list(data["exclude_entities_raw"]),
        exclude_entity_id_regex=eid_regex.joined,
        exclude_entity_id_regex_lines=eid_regex.lines,
        exclude_entity_name_regex=name_regex.joined,
        exclude_entity_name_regex_lines=name_regex.lines,
        check_interval_minutes=data["check_interval_minutes_raw"],
        validate_includes_excludes=data["validate_includes_excludes_raw"],
        debug_logging=data["debug_logging_raw"],
    )


# --------------------------------------------------------
# Layer 3: service layer
# --------------------------------------------------------


async def _async_service_layer(
    hass: HomeAssistant,
    _call: ServiceCall,
    *,
    now: datetime,
    instance_id: str,
    trigger_id: str,
    warning_level: int,
    include_integrations: list[str],
    exclude_integrations: list[str],
    exclude_device_name_regex: str,
    exclude_device_name_regex_lines: list[JoinedRegexLine],
    include_entities: list[str],
    exclude_entities: list[str],
    exclude_entity_id_regex: str,
    exclude_entity_id_regex_lines: list[JoinedRegexLine],
    exclude_entity_name_regex: str,
    exclude_entity_name_regex_lines: list[JoinedRegexLine],
    check_interval_minutes: int,
    validate_includes_excludes: bool,
    debug_logging: bool,
) -> None:
    """Run a scan + dispatch notifications + persist diagnostics."""
    state = _instances(hass).setdefault(
        instance_id,
        BwInstanceState(instance_id=instance_id),
    )
    entry = entry_for_domain(hass)
    if entry is not None:
        _ensure_timer(hass, entry, state, check_interval_minutes)

    notif_prefix = notification_prefix(_SERVICE, instance_id)
    config = logic.Config(
        warning_level=warning_level,
        include_integrations=frozenset(include_integrations),
        exclude_integrations=frozenset(exclude_integrations),
        include_entities=frozenset(include_entities),
        exclude_entities=frozenset(exclude_entities),
        exclude_device_name_regex=exclude_device_name_regex,
        exclude_entity_id_regex=exclude_entity_id_regex,
        exclude_entity_name_regex=exclude_entity_name_regex,
        notification_prefix=notif_prefix,
        instance_id=instance_id,
    )
    directive_inputs = logic.DirectiveInputs(
        enabled=validate_includes_excludes,
        include_integrations=include_integrations,
        exclude_integrations=exclude_integrations,
        include_entities=include_entities,
        exclude_entities=exclude_entities,
        exclude_device_name_regex_lines=exclude_device_name_regex_lines,
        exclude_entity_id_regex_lines=exclude_entity_id_regex_lines,
        exclude_entity_name_regex_lines=exclude_entity_name_regex_lines,
    )

    ev = logic.run_evaluation(config, _battery_inputs(hass), directive_inputs)

    unmatched_spec = make_unmatched_directives_notification(
        service=_SERVICE,
        instance_id=instance_id,
        unmatched=ev.unmatched_directives,
    )
    await process_persistent_notifications_with_sweep(
        hass,
        [ev.notification, unmatched_spec],
        sweep_prefix=notif_prefix,
    )

    update_instance_state(
        hass,
        service_tag=_SERVICE_TAG,
        instance_id=instance_id,
        last_run=now,
        runtime=(dt_util.now() - now).total_seconds(),
        extra_attributes={
            "last_trigger": trigger_id or "",
            "batteries": ev.batteries,
            "batteries_excluded": ev.batteries_excluded,
            "low_batteries": len(ev.low),
            "low_battery_entities": sorted(b.entity_id for b in ev.low),
            "unmatched_directives": len(ev.unmatched_directives),
        },
    )

    if debug_logging:
        tag = f"[{_SERVICE_TAG}: {automation_friendly_name(hass, instance_id)}]"
        _LOGGER.warning(
            "%s batteries=%d excluded=%d low=%d unmatched_directives=%d",
            tag,
            ev.batteries,
            ev.batteries_excluded,
            len(ev.low),
            len(ev.unmatched_directives),
        )


def _battery_inputs(hass: HomeAssistant) -> list[logic.BatteryInfo]:
    """Every battery-class entity with a state, with its context.

    A battery's device carries every integration with an
    entity on it, so the logic can drop a whole device when
    one of them is excluded.
    """
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    device_integrations: dict[str, set[str]] = {}
    for registered in ent_reg.entities.values():
        if registered.device_id is not None and registered.platform:
            device_integrations.setdefault(registered.device_id, set()).add(
                registered.platform
            )

    batteries: list[logic.BatteryInfo] = []
    for st in hass.states.async_all(_BATTERY_DOMAINS):
        if st.attributes.get("device_class") != "battery":
            continue
        reg_entry = ent_reg.async_get(st.entity_id)
        device_entry = (
            dev_reg.async_get(reg_entry.device_id)
            if reg_entry is not None and reg_entry.device_id is not None
            else None
        )
        device = (
            logic.BatteryDevice(
                device_id=device_entry.id,
                name=(
                    device_entry.name_by_user
                    or device_entry.name
                    or device_entry.id
                ),
                integrations=frozenset(
                    device_integrations.get(device_entry.id, ())
                ),
            )
            if device_entry is not None
            else None
        )
        batteries.append(
            logic.BatteryInfo(
                entity_id=st.entity_id,
                name=st.name,
                integration=reg_entry.platform if reg_entry else "",
                state=st.state,
                binary=st.domain == "binary_sensor",
                device=device,
                area=entity_area_name(hass, st.entity_id),
            )
        )
    return batteries


# --------------------------------------------------------
# Periodic timer
# --------------------------------------------------------


def _ensure_timer(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: BwInstanceState,
    interval_minutes: int,
) -> None:
    """(Re)arm the periodic timer if the interval changed."""
    if state.armed_interval_minutes == interval_minutes:
        return
    if state.cancel_timer is not None:
        state.cancel_timer()
        state.cancel_timer = None
    state.armed_interval_minutes = interval_minutes
    state.cancel_timer = schedule_periodic_with_jitter(
        hass,
        entry,
        interval=timedelta(minutes=interval_minutes),
        instance_id=state.instance_id,
        action=make_periodic_trigger_callback(
            hass,
            state.instance_id,
            instances_getter=_instances,
            service_tag=_SERVICE_TAG,
            logger=_LOGGER,
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
    reset_armed_interval_on_reload=True,
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
    kick_variables={"trigger_id": "manual"},
    on_reload=_on_reload,
    on_entity_remove=_on_entity_remove,
    on_entity_rename=_on_entity_rename,
    on_teardown=_on_teardown,
)


async def async_register(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Register BW's service + lifecycle via the shared helper."""
    await register_blueprint_handler(hass, entry, _SPEC)


async def async_unregister(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Tear down BW's service + lifecycle via the shared helper."""
    await unregister_blueprint_handler(hass, entry, _SPEC)


__all__ = [
    "BLUEPRINT_PATH",
    "BwInstanceState",
    "async_register",
    "async_unregister",
]
