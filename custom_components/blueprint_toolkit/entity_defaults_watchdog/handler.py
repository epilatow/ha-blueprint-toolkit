# This is AI generated code
"""HA wiring for entity_defaults_watchdog.

EDW-specific shape on top of the standard three-layer
dispatch (see ``DEVELOPMENT.md`` for the universal
pattern):

- Periodic scan via integration-owned scheduling. The
  blueprint's ``time_pattern`` minute trigger is gone;
  ``helpers.schedule_periodic_with_jitter`` arms a per-
  instance offset so multiple instances of this blueprint
  don't hammer the registries simultaneously on shared
  intervals.
- Truth set (entity registry, device registry, target-
  integration filter, deviceless peers) is built on the
  event loop because HA registries are loop-only. Heavy
  work (per-device drift classification, deviceless
  collision-suffix scan, notification body assembly)
  runs in the executor via
  ``hass.async_add_executor_job(logic.run_evaluation, ...)``.
- Three finding streams: per-device drift, a single
  deviceless aggregate, and visible-aliased entities. The
  logic builds device-attached drift as either repair
  issues (when ``create_repairs`` is on -- one per drift
  kind per device) or the aggregate per-device notification
  (when off, capped by ``max_device_notifications`` via
  ``helpers.prepare_notifications``) -- never both. The
  deviceless + visible-aliased streams are notification-only
  (no automatable fix). The complete per-instance batch is
  sweep-dispatched via ``process_repairs_with_sweep`` so
  prior-run findings no longer present this run get cleaned
  up from both the notification surface and the issue
  registry.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
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
    all_integration_ids,
    automation_friendly_name,
    cv_ha_domain_list,
    entry_for_domain,
    integration_entity_ids,
    make_emit_config_error,
    make_lifecycle_mutators,
    make_periodic_trigger_callback,
    make_unmatched_directives_notification,
    notification_prefix,
    process_repairs_with_sweep,
    register_blueprint_handler,
    register_fix_service,
    resolve_target_integrations,
    schedule_periodic_with_jitter,
    spec_bucket,
    unregister_blueprint_handler,
    update_instance_state,
    validate_and_join_regex_patterns,
    validate_payload_or_emit_config_error,
)
from . import logic

_LOGGER = logging.getLogger(__name__)

_SERVICE = "entity_defaults_watchdog"
_SERVICE_TAG = "EDW"
_SERVICE_NAME = "Entity Defaults Watchdog"
BLUEPRINT_PATH = "blueprint_toolkit/entity_defaults_watchdog.yaml"


# --------------------------------------------------------
# Per-instance in-memory state
# --------------------------------------------------------


@dataclass
class EdwInstanceState:
    """In-memory state for one EDW automation instance.

    Lost on HA restart; the periodic timer + restart-
    recovery kick re-arm everything from scratch on the
    next tick.
    """

    instance_id: str
    # Tracks the interval the timer was last armed with so
    # we can detect blueprint-input changes and re-arm.
    armed_interval_minutes: int = 0
    cancel_timer: Callable[[], None] | None = field(default=None, repr=False)
    # Per-repair rich payloads, populated by the service
    # layer on every scan. Keyed by the repair's
    # ``notification_id``; each value carries everything
    # the fix service needs to apply (per-entity rename
    # list, per-entity name-target list, ...). The fix
    # service looks up by notification_id and applies
    # verbatim -- no re-scoping at apply time, because the
    # scan that built this entry already applied the
    # user's full filter configuration. Empty default
    # keeps the post-restart window safe: a fix click
    # before the next scan finds no payload and no-ops.
    repairs: dict[str, logic.EdwRepair] = field(default_factory=dict)


# --------------------------------------------------------
# Service-call schema
# --------------------------------------------------------

_SCHEMA = vol.Schema(
    {
        vol.Required("instance_id"): cv.entity_id,
        vol.Required("trigger_id"): vol.Coerce(str),
        vol.Required("drift_checks_raw"): vol.All(
            cv.ensure_list, [vol.Coerce(str)]
        ),
        vol.Required("include_integrations_raw"): cv_ha_domain_list,
        vol.Required("exclude_integrations_raw"): cv_ha_domain_list,
        vol.Required("exclude_device_name_regex_raw"): vol.Coerce(str),
        vol.Required("exclude_entities_raw"): cv.entity_ids,
        vol.Required("exclude_entity_id_regex_raw"): vol.Coerce(str),
        vol.Required("exclude_entity_name_regex_raw"): vol.Coerce(str),
        vol.Required("check_interval_minutes_raw"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=10080)
        ),
        vol.Required("max_device_notifications_raw"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=1000)
        ),
        vol.Required("create_repairs_raw"): cv.boolean,
        vol.Required("max_repairs_raw"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=1000)
        ),
        vol.Required("validate_includes_excludes_raw"): cv.boolean,
        vol.Required("debug_logging_raw"): cv.boolean,
    },
    extra=vol.ALLOW_EXTRA,
)


# --------------------------------------------------------
# Per-instance state accessor
# --------------------------------------------------------


def _instances(hass: HomeAssistant) -> dict[str, EdwInstanceState]:
    """Per-instance state map under our service's bucket."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {}
    bucket = spec_bucket(entries[0], _SERVICE)
    instances: dict[str, EdwInstanceState] = bucket.setdefault("instances", {})
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

    # Drift-check cross-validation: each requested check
    # must be in CHECK_ALL. Empty list means "all checks"
    # (mirrors the include_integrations empty-means-all
    # pattern in this same handler).
    drift_checks_raw: list[str] = list(data["drift_checks_raw"])
    unknown_checks = [c for c in drift_checks_raw if c not in logic.CHECK_ALL]
    if unknown_checks:
        bad = ", ".join(sorted(unknown_checks))
        valid = ", ".join(sorted(logic.CHECK_ALL))
        errors.append(
            f"drift_checks: unknown value(s) {bad}. Valid values: {valid}."
        )
    drift_checks: frozenset[str] = (
        logic.CHECK_ALL if not drift_checks_raw else frozenset(drift_checks_raw)
    )

    # Multi-line regex inputs go through the shared helper
    # so per-line ``re.compile`` validation, empty-match
    # rejection, and alternation join behave identically.
    # See ``test_helpers_lifecycle.TestValidateAndJoinRegexPatterns``
    # for the parser contract.
    dev_regex_result = validate_and_join_regex_patterns(
        data["exclude_device_name_regex_raw"],
        "exclude_device_name_regex",
    )
    exclude_device_name_regex = dev_regex_result.joined
    errors.extend(dev_regex_result.errors)
    eid_regex_result = validate_and_join_regex_patterns(
        data["exclude_entity_id_regex_raw"],
        "exclude_entity_id_regex",
    )
    exclude_entity_id_regex = eid_regex_result.joined
    errors.extend(eid_regex_result.errors)
    en_regex_result = validate_and_join_regex_patterns(
        data["exclude_entity_name_regex_raw"],
        "exclude_entity_name_regex",
    )
    exclude_entity_name_regex = en_regex_result.joined
    errors.extend(en_regex_result.errors)

    # Argparse complete; emit accumulated errors (or
    # dismiss any prior config_error notification).
    await _emit_config_error(hass, instance_id, errors)
    if errors:
        return

    await _async_service_layer(
        hass,
        call,
        now=now,
        instance_id=instance_id,
        trigger_id=data["trigger_id"],
        drift_checks=drift_checks,
        include_integrations=list(data["include_integrations_raw"]),
        exclude_integrations=list(data["exclude_integrations_raw"]),
        exclude_device_name_regex=exclude_device_name_regex,
        exclude_device_name_regex_lines=dev_regex_result.lines,
        exclude_entities=list(data["exclude_entities_raw"]),
        exclude_entity_id_regex=exclude_entity_id_regex,
        exclude_entity_id_regex_lines=eid_regex_result.lines,
        exclude_entity_name_regex=exclude_entity_name_regex,
        exclude_entity_name_regex_lines=en_regex_result.lines,
        check_interval_minutes=data["check_interval_minutes_raw"],
        max_notifications=data["max_device_notifications_raw"],
        create_repairs=data["create_repairs_raw"],
        max_repairs=data["max_repairs_raw"],
        validate_includes_excludes=data["validate_includes_excludes_raw"],
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
    drift_checks: frozenset[str],
    include_integrations: list[str],
    exclude_integrations: list[str],
    exclude_device_name_regex: str,
    exclude_device_name_regex_lines: list[JoinedRegexLine],
    exclude_entities: list[str],
    exclude_entity_id_regex: str,
    exclude_entity_id_regex_lines: list[JoinedRegexLine],
    exclude_entity_name_regex: str,
    exclude_entity_name_regex_lines: list[JoinedRegexLine],
    check_interval_minutes: int,
    max_notifications: int,
    create_repairs: bool,
    max_repairs: int,
    validate_includes_excludes: bool,
    debug_logging: bool,
) -> None:
    """Run a scan + dispatch notifications + persist diagnostics."""
    state = _instances(hass).setdefault(
        instance_id,
        EdwInstanceState(instance_id=instance_id),
    )
    # Make sure the periodic timer is armed with the
    # current interval (handles first-run + interval
    # changes mid-flight).
    entry = entry_for_domain(hass)
    if entry is not None:
        _ensure_timer(hass, entry, state, check_interval_minutes)

    notif_prefix = notification_prefix(_SERVICE, instance_id)
    tag = f"[{_SERVICE_TAG}: {automation_friendly_name(hass, instance_id)}]"

    config = logic.Config(
        drift_checks=drift_checks,
        exclude_device_name_regex=exclude_device_name_regex,
        exclude_entity_ids=exclude_entities,
        exclude_entity_id_regex=exclude_entity_id_regex,
        exclude_entity_name_regex=exclude_entity_name_regex,
        create_repairs=create_repairs,
        notification_prefix=notif_prefix,
        instance_id=instance_id,
    )

    # Resolve target integrations + assemble inputs on the
    # event loop -- the registries we walk are loop-only.
    all_integrations = all_integration_ids(hass)
    target_integrations = resolve_target_integrations(
        all_integrations,
        include_integrations,
        exclude_integrations,
    )
    devices = _build_device_inputs(
        hass,
        all_integrations,
        target_integrations,
    )
    deviceless_entities, peers_by_domain = _build_deviceless_inputs(
        hass,
        logic.DEVICELESS_DOMAINS,
        target_integrations,
    )
    # Visible-aliased inputs come from the switch_as_x
    # config entries, not the entity registry walk -- the
    # source-entity hide is keyed off the wrapper config
    # entry, so the entry list is the natural starting
    # point. Defensive-check skips (entry disabled,
    # malformed options, wrapper missing, source disabled,
    # source already hidden) get filtered out at the
    # builder so the logic layer only sees genuinely
    # candidate sources.
    visible_aliased_infos, visible_aliased_defensive_skipped = (
        _build_visible_aliased_inputs(hass)
    )

    # Candidate sets for the directive validators. Sourced
    # from the FULL device + entity registries (NOT filtered
    # by include / exclude integrations). Reason: the
    # integration filter and the regex / entity-id filters
    # are independent layers from the user's perspective;
    # measuring the regex against a post-integration set
    # would surface "matches nothing" warnings whenever the
    # integration filter already pruned the entities the
    # regex would have caught -- a confusing leak of
    # internal layer ordering.
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    all_registered_entity_ids = frozenset(ent_reg.entities)
    device_name_candidates: frozenset[str] = frozenset(
        name
        for d in dev_reg.devices.values()
        if (name := d.name_by_user or d.name)
    )
    entity_id_candidates = all_registered_entity_ids
    entity_name_candidates: frozenset[str] = frozenset(
        v
        for e in ent_reg.entities.values()
        for v in (e.name, e.original_name)
        if v
    )

    directive_inputs = logic.DirectiveInputs(
        enabled=validate_includes_excludes,
        include_integrations=include_integrations,
        exclude_integrations=exclude_integrations,
        exclude_entities=exclude_entities,
        all_registered_entity_ids=all_registered_entity_ids,
        exclude_device_name_regex_lines=exclude_device_name_regex_lines,
        exclude_entity_id_regex_lines=exclude_entity_id_regex_lines,
        exclude_entity_name_regex_lines=exclude_entity_name_regex_lines,
        device_name_candidates=device_name_candidates,
        entity_id_candidates=entity_id_candidates,
        entity_name_candidates=entity_name_candidates,
    )

    # Heavy work (per-device drift classification,
    # deviceless collision-suffix scan, notification body
    # assembly, directive validation) runs in HA's
    # executor pool so the event loop stays responsive.
    ev = await hass.async_add_executor_job(
        logic.run_evaluation,
        config,
        devices,
        deviceless_entities,
        peers_by_domain,
        all_integrations,
        max_notifications,
        directive_inputs,
        visible_aliased_infos,
    )

    unmatched_spec = make_unmatched_directives_notification(
        service=_SERVICE,
        instance_id=instance_id,
        unmatched=ev.unmatched_directives,
    )

    # The logic already built the device-attached drift as
    # either repair-carrying specs (when ``create_repairs``
    # is on) or the aggregate per-device notification (when
    # off) -- never both -- inside ``ev.notifications``,
    # plus the matching per-repair payloads in ``ev.repairs``.
    # Dispatch the whole batch; the unmatched-directives
    # spec is appended outside the per-device cap so a
    # typo'd exclusion always surfaces.
    published_repair_ids = await process_repairs_with_sweep(
        hass,
        list(ev.notifications) + [unmatched_spec],
        sweep_prefix=notif_prefix,
        create_repairs=create_repairs,
        repair_cap=max_repairs,
    )
    # Keep only payloads for repairs that actually landed in
    # the issue registry (the dispatcher's cap can suppress
    # some). An external service-call dispatch against a
    # notification_id the user can't see in the Repairs panel
    # should be a no-op, not silently apply a hidden fix.
    state.repairs = {
        nid: payload
        for nid, payload in ev.repairs.items()
        if nid in published_repair_ids
    }

    # Persist diagnostic state.
    update_instance_state(
        hass,
        service_tag=_SERVICE_TAG,
        instance_id=instance_id,
        last_run=now,
        runtime=(dt_util.now() - now).total_seconds(),
        extra_attributes={
            "last_trigger": trigger_id or "",
            "integrations": ev.all_integrations_count,
            "integrations_excluded": (
                ev.all_integrations_count - len(target_integrations)
            ),
            "devices": len(ev.results),
            "devices_excluded": ev.stat_devices_excluded,
            "entities": ev.stat_entities,
            "entities_excluded": ev.stat_entities_excluded,
            "device_issues": ev.issues_count,
            "entity_issues": ev.stat_entity_issues,
            "entity_name_issues": ev.stat_name_issues,
            "entity_id_issues": ev.stat_id_issues,
            "deviceless_entities": ev.stat_deviceless_entities,
            "deviceless_excluded": ev.stat_deviceless_excluded,
            "deviceless_drift": ev.stat_deviceless_drift,
            "deviceless_stale": ev.stat_deviceless_stale,
            # ``kept + excluded`` is ``len(infos)`` -- every
            # candidate the handler handed to the logic
            # layer. Adding the handler-side defensive-skip
            # count gives the total number of switch_as_x
            # entries walked.
            "visible_aliased_total": (
                ev.stat_visible_aliased_kept
                + ev.stat_visible_aliased_excluded
                + visible_aliased_defensive_skipped
            ),
            "visible_aliased_excluded": (
                ev.stat_visible_aliased_excluded
                + visible_aliased_defensive_skipped
            ),
            "visible_aliased_flagged": (ev.stat_visible_aliased_flagged),
            "unmatched_directives": len(ev.unmatched_directives),
        },
    )

    if debug_logging:
        _LOGGER.warning(
            "%s integrations=%d devices=%d entities=%d"
            " device_issues=%d entity_issues=%d"
            " deviceless_drift=%d deviceless_stale=%d"
            " unmatched_directives=%d",
            tag,
            ev.all_integrations_count,
            len(ev.results),
            ev.stat_entities,
            ev.issues_count,
            ev.stat_entity_issues,
            ev.stat_deviceless_drift,
            ev.stat_deviceless_stale,
            len(ev.unmatched_directives),
        )


# --------------------------------------------------------
# Truth-set assembly (event-loop only)
# --------------------------------------------------------


def _build_device_inputs(
    hass: HomeAssistant,
    all_integration_ids: list[str],
    target_integrations: set[str],
) -> list[logic.DeviceInfo]:
    """Walk registries to build ``DeviceInfo`` per device.

    Always scans every integration so multi-integration
    detection (which gates the recommended-override path)
    stays accurate. ``target_integrations`` filters which
    integrations populate entity drift snapshots; the
    device's ``integration_entities`` map carries every
    integration the device touches but only the targeted
    ones contribute ``EntityDriftInfo`` rows.

    ``all_integration_ids`` is threaded in by the caller
    (already computed for filter resolution) so we don't
    re-walk the entity registry here just to enumerate
    integrations.
    """
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    device_map: dict[str, logic.DeviceEntry] = {}
    # Map device_id -> {integration_id -> [entity_id]} for
    # the entities we want full drift snapshots on.
    populate_eids: dict[str, dict[str, list[str]]] = {}

    for integration_id in all_integration_ids:
        entity_ids = integration_entity_ids(hass, integration_id)
        for entity_id in entity_ids:
            entry = ent_reg.async_get(entity_id)
            if entry is None or entry.device_id is None:
                continue
            if entry.disabled_by is not None:
                continue
            device = dev_reg.async_get(entry.device_id)
            if device is None:
                continue
            dev_id = entry.device_id
            if dev_id not in device_map:
                device_map[dev_id] = logic.DeviceEntry(
                    id=dev_id,
                    name=device.name_by_user or device.name or "",
                    default_name=device.name or "",
                )
                populate_eids[dev_id] = {}
            ie = device_map[dev_id].integration_entities
            if integration_id not in ie:
                ie[integration_id] = set()
            if integration_id in target_integrations:
                ie[integration_id].add(entity_id)
                populate_eids[dev_id].setdefault(integration_id, []).append(
                    entity_id
                )

    devices: list[logic.DeviceInfo] = []
    for dev_id, dev_entry in device_map.items():
        entity_infos: list[logic.EntityDriftInfo] = []
        for eids in populate_eids.get(dev_id, {}).values():
            for eid in eids:
                entry = ent_reg.async_get(eid)
                if entry is None:
                    continue
                expected_id = str(ent_reg.async_regenerate_entity_id(entry))
                has_name_override = entry.name is not None
                current_name = str(
                    entry.name or entry.original_name or "",
                )
                expected_name: str | None = None
                if has_name_override:
                    expected_name = str(entry.original_name or "")
                entity_infos.append(
                    logic.EntityDriftInfo(
                        entity_id=eid,
                        has_entity_name=entry.has_entity_name,
                        has_name_override=has_name_override,
                        expected_entity_id=expected_id,
                        current_name=current_name,
                        expected_name=expected_name,
                    ),
                )
        devices.append(
            logic.DeviceInfo(de=dev_entry, entities=entity_infos),
        )
    return devices


def _default_friendly_name(obj_id: str) -> str:
    """HA-style default friendly name for an ``obj_id``.

    Mirrors what HA shows for an entity lacking a
    ``friendly_name`` attribute: underscores become spaces
    and the result is title-cased. ``slugify`` round-trips
    this back to ``obj_id`` so a deviceless entity with no
    explicit name is classified as non-drifting by default.
    """
    return obj_id.replace("_", " ").title()


def _build_deviceless_inputs(
    hass: HomeAssistant,
    domains: frozenset[str],
    target_integrations: set[str] | None,
) -> tuple[list[logic.DevicelessEntityInfo], dict[str, set[str]]]:
    """Walk registry + state list for deviceless entities.

    Primary source: entity registry entries where
    ``device_id is None`` and domain is in ``domains``.
    Supplementary source: state-list entities in the same
    domains not present in the registry at all (YAML-
    defined entities without ``unique_id:``) -- caught via
    their state's ``friendly_name`` attribute.

    ``target_integrations`` optionally restricts the
    registry-backed slice to entries whose ``platform`` is
    in the set. State-only entries have no platform and
    are unaffected by this filter; ``None`` means no
    filtering.

    Returns ``(entities, peers_by_domain)``. ``peers`` is
    the union of registry and state-only object_ids per
    domain and is NOT integration-filtered, so the logic
    module's collision-suffix classifier still sees every
    peer that could justify a ``_N`` suffix.
    """
    entities: list[logic.DevicelessEntityInfo] = []
    peers: dict[str, set[str]] = {}
    # Track every registry entity_id (including device-
    # attached and disabled entries) so the state-list
    # safety net only picks up entities that truly have
    # no registry entry.
    seen_eids: set[str] = set()

    ent_reg = er.async_get(hass)
    for entry in ent_reg.entities.values():
        seen_eids.add(entry.entity_id)
        if entry.device_id is not None:
            continue
        if entry.disabled_by is not None:
            continue
        dom, obj = entry.entity_id.split(".", 1)
        if dom not in domains:
            continue
        # Add to peers BEFORE the integration filter so
        # collision-suffix detection still sees filtered
        # peers (otherwise a ``foo_2`` whose ``foo`` peer
        # was filtered out would be falsely flagged as
        # stale).
        peers.setdefault(dom, set()).add(obj)
        if (
            target_integrations is not None
            and entry.platform
            and entry.platform not in target_integrations
        ):
            continue
        effective = str(
            entry.name or entry.original_name or _default_friendly_name(obj),
        )
        entities.append(
            logic.DevicelessEntityInfo(
                entity_id=entry.entity_id,
                effective_name=effective,
                platform=entry.platform,
                unique_id=entry.unique_id,
                from_registry=True,
                config_entry_id=entry.config_entry_id,
            ),
        )

    # State-only safety net -- YAML entities without a
    # unique_id don't appear in the registry but do have
    # state. friendly_name comparison: when it equals HA's
    # default (title-cased obj_id) slugify will match
    # obj_id exactly and the logic module won't flag it.
    for st in hass.states.async_all():
        eid = st.entity_id
        if eid in seen_eids:
            continue
        dom, obj = eid.split(".", 1)
        if dom not in domains:
            continue
        try:
            fn = str(st.attributes.get("friendly_name", "") or "")
        except (AttributeError, TypeError):
            continue
        if not fn:
            fn = _default_friendly_name(obj)
        entities.append(
            logic.DevicelessEntityInfo(
                entity_id=eid,
                effective_name=fn,
                platform=None,
                unique_id=None,
                from_registry=False,
            ),
        )
        peers.setdefault(dom, set()).add(obj)

    return (entities, peers)


# --------------------------------------------------------
# Visible-aliased-entity inputs (event-loop only)
# --------------------------------------------------------
#
# ``switch_as_x`` is HA core's wrapper integration: a user
# exposes ``switch.foo`` as ``fan.foo`` and the integration
# sets ``hidden_by="integration"`` on the source entity once
# at config-entry creation. If ``hidden_by`` is later
# cleared on the source, both rows become visible
# everywhere. This builder discovers the candidate set
# (switch_as_x entries whose source is currently visible)
# and hands it to the logic layer for per-entity exclusion
# + finding emission.


_SWITCH_AS_X_DOMAIN = "switch_as_x"


def _build_visible_aliased_inputs(
    hass: HomeAssistant,
) -> tuple[list[logic.VisibleAliasedEntityInfo], int]:
    """Walk switch_as_x entries; return surviving inputs + defensive-skip count.

    Defensive-skip cases (counted into the returned int, not
    the input list):

    - The whole switch_as_x entry is disabled
      (``entry.disabled_by is not None``) -- skip.
    - ``entry.options`` is malformed (missing
      ``entity_id`` / ``target_domain``, or non-string
      values, or the source isn't registered) -- skip.
    - No registry entry whose
      ``config_entry_id == entry.entry_id`` AND
      ``domain == target_domain`` matches, OR more than one
      such entry matches. Something else has gone sideways
      with the entry; a flag would mislead.
    - The source is disabled in the registry
      (``source.disabled_by is not None``) -- skip.
      Disabled covers the same user-facing symptom (source
      row hidden), so flagging would be a false positive.
    - The source still has ``hidden_by`` set -- this is the
      healthy case. Filtered out at the builder so the
      logic layer's input list maps 1:1 to candidate
      findings.
    """
    ent_reg = er.async_get(hass)
    infos: list[logic.VisibleAliasedEntityInfo] = []
    defensive_skipped = 0

    for entry in hass.config_entries.async_entries(
        _SWITCH_AS_X_DOMAIN,
    ):
        if entry.disabled_by is not None:
            defensive_skipped += 1
            continue

        options: Mapping[str, Any] = entry.options or {}
        source_eid_raw = options.get("entity_id")
        target_domain_raw = options.get("target_domain")
        if not isinstance(source_eid_raw, str) or not source_eid_raw:
            defensive_skipped += 1
            continue
        if not isinstance(target_domain_raw, str) or not target_domain_raw:
            defensive_skipped += 1
            continue

        source = ent_reg.async_get(source_eid_raw)
        if source is None:
            defensive_skipped += 1
            continue

        # Filter wrapper candidates by both ``config_entry_id``
        # and ``target_domain`` so the lookup remains stable if
        # a switch_as_x entry ever registers more than one
        # entity (today HA core registers exactly one per
        # entry; the registry walk order isn't guaranteed
        # stable across HA versions).
        wrapper_matches = [
            e
            for e in ent_reg.entities.values()
            if e.config_entry_id == entry.entry_id
            and e.domain == target_domain_raw
        ]
        if len(wrapper_matches) != 1:
            defensive_skipped += 1
            continue
        wrapper = wrapper_matches[0]

        if source.disabled_by is not None:
            defensive_skipped += 1
            continue

        # Healthy case: integration- (or user-) hidden source
        # is filtered out here. Logic only sees candidates
        # whose source is visible, mapping 1:1 to findings
        # before user exclusions.
        if source.hidden_by is not None:
            defensive_skipped += 1
            continue

        wrapper_obj_id = wrapper.entity_id.split(".", 1)[1]
        friendly = str(
            source.name or source.original_name or source_eid_raw,
        )
        infos.append(
            logic.VisibleAliasedEntityInfo(
                source_entity_id=source_eid_raw,
                wrapper_entity_id=wrapper_obj_id,
                wrapper_target_domain=target_domain_raw,
                wrapper_title=str(entry.title or ""),
                source_friendly_name=friendly,
                source_device_id=source.device_id,
                source_config_entry_id=source.config_entry_id,
            ),
        )

    return infos, defensive_skipped


# --------------------------------------------------------
# Periodic timer + recovery kick
# --------------------------------------------------------


def _ensure_timer(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: EdwInstanceState,
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
    """Register EDW's service + lifecycle via the shared helper."""
    await register_blueprint_handler(hass, entry, _SPEC)


async def async_unregister(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Tear down EDW's service + lifecycle via the shared helper."""
    await unregister_blueprint_handler(hass, entry, _SPEC)


# --------------------------------------------------------
# Repair fix services
# --------------------------------------------------------

FIX_SERVICES: tuple[str, ...] = tuple(s.value for s in logic.FixServices)


def _lookup_repair(
    hass: HomeAssistant,
    notification_id: str,
) -> logic.EdwRepair | None:
    """Find the per-repair payload across all loaded EDW instances."""
    for inst in _instances(hass).values():
        payload = inst.repairs.get(notification_id)
        if payload is not None:
            return payload
    return None


async def async_register_fix_services(hass: HomeAssistant) -> None:
    """Register EDW's per-device repair fix services.

    ``register_fix_service`` owns the shared contract
    (``notification_id`` schema, idempotent ``has_service``
    guard, crash-PN wrap, id decoding), so each fix is just
    ``async def (notification_id: str)``.

    Each fix service looks up its rich payload by
    ``notification_id`` on the per-instance state. The
    payload was built at scan time with the user's full
    filter configuration in scope, so the fix service
    re-applies the captured mutations verbatim without any
    re-scoping. A click after restart (instance state lost)
    or after the next scan removed the finding (payload
    cleared) finds nothing and no-ops; the issue is
    rebuilt or swept on the next periodic tick.
    """

    async def _fix_id_drift(notification_id: str) -> None:
        payload = _lookup_repair(hass, notification_id)
        if not isinstance(payload, logic.DeviceEntityIdDriftRepair):
            return
        ent_reg = er.async_get(hass)
        for entity_id, expected_id in payload.entity_renames:
            entry = ent_reg.async_get(entity_id)
            if entry is None or entry.entity_id == expected_id:
                continue
            ent_reg.async_update_entity(entity_id, new_entity_id=expected_id)

    async def _fix_name_drift(notification_id: str) -> None:
        payload = _lookup_repair(hass, notification_id)
        if not isinstance(payload, logic.DeviceEntityNameDriftRepair):
            return
        ent_reg = er.async_get(hass)
        for entity_id, target in payload.entity_name_targets:
            entry = ent_reg.async_get(entity_id)
            if entry is None or entry.name == target:
                continue
            ent_reg.async_update_entity(entity_id, name=target)

    async def _fix_visible_aliased(notification_id: str) -> None:
        payload = _lookup_repair(hass, notification_id)
        if not isinstance(payload, logic.VisibleAliasedEntityRepair):
            return
        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get(payload.source_entity_id)
        hidden = er.RegistryEntryHider.INTEGRATION
        if entry is None or entry.hidden_by is hidden:
            return
        ent_reg.async_update_entity(
            payload.source_entity_id,
            hidden_by=hidden,
        )

    register_fix_service(
        hass,
        logic.FixServices.DEVICE_ENTITY_ID_DRIFT,
        _fix_id_drift,
    )
    register_fix_service(
        hass,
        logic.FixServices.DEVICE_ENTITY_NAME_DRIFT,
        _fix_name_drift,
    )
    register_fix_service(
        hass,
        logic.FixServices.VISIBLE_ALIASED_ENTITY,
        _fix_visible_aliased,
    )


__all__ = [
    "BLUEPRINT_PATH",
    "FIX_SERVICES",
    "EdwInstanceState",
    "async_register",
    "async_register_fix_services",
    "async_unregister",
]
