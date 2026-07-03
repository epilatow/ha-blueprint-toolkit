# This is AI generated code
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest-homeassistant-custom-component==0.13.357",
#     "zwave-js-server-python==0.73.0",
#     "voluptuous",
#     "pyyaml",
#     "types-PyYAML",
# ]
# ///
"""Z-Wave Parameter Manager handler.

Reconciles each Z-Wave node's settable config parameters against a
declarative policy file, in-process via HA's ``zwave_js`` driver. The
three-layer split (entrypoint -> argparse -> service layer) mirrors the
other handlers; the reconcile body runs the shared ``pipeline`` (load the
policy file + the shipped mapping, then plan + build the report -- the same
pipeline ``zwavectl`` runs) over ``source.read_fleet`` (the live fleet off
the in-process driver), then applies ``apply.select_writes`` (which to issue
this cycle) and emits the ``notification`` reports.

Pending state -- the writes issued but not yet seen converge -- lives in the
shared ``zpm_pending.json`` (see ``pending_store``), keyed off the
driver-session record's ``last_reset_at`` (see ``zwave.driver_session``): a
write is suppressed only while it was issued after the last Z-Wave JS driver
restart, the event that flushes the device wake-up queue. The same file backs
the CLI's ``apply``, so the two never double-issue. The handler refreshes the
driver-session record each reconcile, so a driver restart -- even one during
an HA Core downtime -- is detected on the next reconcile and every still-
mismatched write re-issues.

Reporting: the pending report is a periodic status. It appears as soon as
a parameter is pending and dismisses the moment the fleet converges; while
anything stays pending it re-publishes on the configured interval (the
``pending_report_interval_hours`` input; 0 disables it). Publishing on an
interval rather than every reconcile keeps the body's per-device wake
estimates -- which drift as sleeping devices wake -- from churning it to
the top of the panel. The desired-config report fires only when the policy
file changes or a newly-configured node appears.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .. import session_monitor
from ..const import DOMAIN
from ..helpers import (
    BlueprintHandlerSpec,
    PersistentNotification,
    automation_friendly_name,
    entry_for_domain,
    make_emit_config_error,
    make_lifecycle_mutators,
    make_periodic_trigger_callback,
    md_escape,
    notification_prefix,
    process_persistent_notifications,
    register_blueprint_handler,
    schedule_periodic_with_jitter,
    spec_bucket,
    unregister_blueprint_handler,
    update_instance_state,
    validate_payload_or_emit_config_error,
)
from ..zwave import driver_session
from . import apply, notification, pending_store, pipeline
from . import logic as zpm_logic

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .logic import ParamId, PlanIssue, PlannedWrite

_LOGGER = logging.getLogger(__name__)

_SERVICE = "zwave_parameter_manager"
_SERVICE_TAG = "ZPM"
_SERVICE_NAME = "Z-Wave Parameter Manager"
BLUEPRINT_PATH = "blueprint_toolkit/zwave_parameter_manager.yaml"

# trigger_id values the blueprint action supplies: "periodic" from the
# integration-owned timer, "manual" otherwise (dev-tools call, the
# restart-recovery + reload kicks, and the reconnect re-trigger).
_TRIGGER_VALUES = ("periodic", "manual")


# --------------------------------------------------------
# Per-instance in-memory state
# --------------------------------------------------------


@dataclass
class ZpmInstanceState:
    """In-memory state for one ZPM automation instance.

    Pending state is NOT here -- it lives in the shared ``zpm_pending.json``
    (see ``pending_store``). ``last_configured_nodes`` and ``last_config_mtime``
    gate when the desired-config report re-fires. Only transient state lives
    here; diagnostics go through ``update_instance_state``.
    """

    instance_id: str
    last_config_mtime: float = 0.0
    last_configured_nodes: frozenset[int] = frozenset()
    # When the pending report was last published, gating its periodic
    # re-publish. ``None`` means nothing is currently published (a fresh
    # instance, or the report was dismissed on convergence / disabled), so the
    # next reconcile with something pending publishes promptly.
    last_pending_publish_dt: datetime | None = None
    last_reconcile_dt: datetime | None = None
    armed_interval_minutes: int = 0
    cancel_timer: Callable[[], None] | None = field(default=None, repr=False)
    cancel_dispatcher: Callable[[], None] | None = field(
        default=None, repr=False
    )
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


def _instances(hass: HomeAssistant) -> dict[str, ZpmInstanceState]:
    """Per-instance state map under our service's bucket."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {}
    bucket = spec_bucket(entries[0], _SERVICE)
    instances: dict[str, ZpmInstanceState] = bucket.setdefault("instances", {})
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


_SCHEMA = vol.Schema(
    {
        vol.Required("instance_id"): cv.entity_id,
        vol.Required("trigger_id"): vol.In(_TRIGGER_VALUES),
        vol.Required("config_file_path"): vol.Coerce(str),
        vol.Required("reconcile_interval_minutes_raw"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=10080)
        ),
        vol.Required("pending_report_interval_hours_raw"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=8760)
        ),
        vol.Required("debug_logging_raw"): cv.boolean,
    },
    extra=vol.ALLOW_EXTRA,
)


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
    """Validate the blueprint inputs, dispatch to the service layer."""
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

    await _async_service_layer(
        hass,
        now=now,
        instance_id=instance_id,
        trigger_id=data["trigger_id"],
        config_file_path=data["config_file_path"],
        reconcile_interval_minutes=data["reconcile_interval_minutes_raw"],
        pending_report_interval_hours=data["pending_report_interval_hours_raw"],
        debug_logging=data["debug_logging_raw"],
    )


# --------------------------------------------------------
# Layer 3: service layer (async reconcile)
# --------------------------------------------------------


async def _async_service_layer(
    hass: HomeAssistant,
    *,
    now: datetime,
    instance_id: str,
    trigger_id: str,
    config_file_path: str,
    reconcile_interval_minutes: int,
    pending_report_interval_hours: int,
    debug_logging: bool,
) -> None:
    """Arm the timer + reconnect hook, then reconcile under the lock."""
    state = _instances(hass).setdefault(
        instance_id,
        ZpmInstanceState(instance_id=instance_id),
    )
    # Serialise timer/subscription wiring + the reconcile body so a manual
    # trigger landing mid-periodic-tick can't race the timer/subscription
    # wiring or another reconcile of this instance.
    async with state.lock:
        entry = entry_for_domain(hass)
        if entry is not None:
            _ensure_timer(hass, entry, state, reconcile_interval_minutes)
        _ensure_reconnect_subscription(hass, state)
        await _do_reconcile(
            hass,
            state,
            now=now,
            trigger_id=trigger_id,
            config_file_path=config_file_path,
            pending_report_interval_hours=pending_report_interval_hours,
            debug_logging=debug_logging,
        )


async def _do_reconcile(
    hass: HomeAssistant,
    state: ZpmInstanceState,
    *,
    now: datetime,
    trigger_id: str,
    config_file_path: str,
    pending_report_interval_hours: int,
    debug_logging: bool,
) -> None:
    from . import source

    instance_id = state.instance_id
    prefix = notification_prefix(_SERVICE, instance_id)
    tag = f"[{_SERVICE_TAG}: {automation_friendly_name(hass, instance_id)}]"

    # Read + parse the policy file (executor I/O). mtime drives the
    # desired-report re-fire; an edit is picked up on the next tick.
    abs_path = _resolve_config_path(hass, config_file_path)
    current_mtime = await hass.async_add_executor_job(_read_mtime, abs_path)
    policies, config_errors = await hass.async_add_executor_job(
        pipeline.load_policies, abs_path
    )

    await _emit_config_error(hass, instance_id, config_errors)
    if config_errors:
        _persist(
            hass,
            state,
            now=now,
            current_mtime=current_mtime,
            trigger_id=trigger_id,
            extra={"config_errors": len(config_errors)},
        )
        return

    mapping, mapping_err = await hass.async_add_executor_job(
        pipeline.load_mapping
    )
    await _dispatch_single(
        hass,
        prefix,
        "internal",
        instance_id,
        "Z-Wave Parameter Manager: internal error",
        mapping_err or "",
        active=mapping_err is not None,
    )
    if mapping is None:
        _persist(
            hass,
            state,
            now=now,
            current_mtime=current_mtime,
            trigger_id=trigger_id,
            extra={"mapping_error": 1},
        )
        return

    reads = await source.read_fleet(hass)
    await _dispatch_single(
        hass,
        prefix,
        "unavailable",
        instance_id,
        "Z-Wave Parameter Manager: Z-Wave JS unavailable",
        "No Z-Wave JS nodes were found. Is the Z-Wave JS integration "
        "loaded and connected?",
        active=not reads,
    )
    if not reads:
        _persist(
            hass,
            state,
            now=now,
            current_mtime=current_mtime,
            trigger_id=trigger_id,
            extra={"devices": 0},
        )
        return

    plan, rep = pipeline.plan_and_report(reads, policies, mapping)
    actuals = {r.device.node_id: r.actuals for r in reads}

    # Refresh the shared driver-session record and read the still-queued
    # pending set from zpm_pending.json. It is empty when the driver restarted
    # since we issued (``last_reset_at`` moved past the file's ``issued_at``),
    # so every mismatched write re-issues. Persisting pending in a shared file
    # lets the CLI's ``apply`` and this handler suppress each other's writes.
    session = await session_monitor.async_refresh(hass, _info_path(hass))
    home_id = session.home_id if session is not None else None
    last_reset_at = session.last_reset_at if session is not None else now
    pending_path = _pending_path(hass)
    if home_id is None:
        pending_map: dict[tuple[int, ParamId], int] = {}
    else:
        pending_map = await hass.async_add_executor_job(
            functools.partial(
                pending_store.read_valid,
                pending_path,
                home_id=home_id,
                last_reset_at=last_reset_at,
            )
        )

    decision = apply.select_writes(plan, actuals, pending_map)
    await _dispatch_writes(hass, decision.writes)

    if home_id is not None:
        plan_keys = frozenset((w.device.node_id, w.id) for w in plan.writes)
        await hass.async_add_executor_job(
            functools.partial(
                pending_store.merge,
                pending_path,
                home_id=home_id,
                last_reset_at=last_reset_at,
                plan_keys=plan_keys,
                decision_pending=decision.pending,
                # UTC so the stamp matches the driver-session record and the
                # CLI's, rather than the handler's local-tz ``now``.
                now=dt_util.as_utc(now),
            )
        )

    issues = [_issue_line(i) for i in (*plan.errors, *plan.warnings)]
    await _dispatch_single(
        hass,
        prefix,
        "plan_issues",
        instance_id,
        "Z-Wave Parameter Manager: policy issues",
        "\n".join(issues),
        active=bool(issues),
    )

    # Desired-config report: only re-fire on a config change or a
    # newly-configured node, so convergence progress doesn't re-bubble it.
    configured = frozenset(w.device.node_id for w in plan.writes)
    if (
        current_mtime != state.last_config_mtime
        or configured != state.last_configured_nodes
    ):
        desired_body = notification.render_report_body(rep, pending_only=False)
        await _dispatch_single(
            hass,
            prefix,
            "desired",
            instance_id,
            "Z-Wave Parameter Manager: desired configuration",
            desired_body,
            active=bool(desired_body),
        )
        state.last_configured_nodes = configured

    # Pending report: a periodic status. Publish as soon as a parameter is
    # pending, then re-publish on ``pending_report_interval_hours`` while it
    # stays pending -- gating on the interval rather than the content keeps a
    # per-device wake estimate (which drifts as sleeping devices wake) from
    # re-bubbling the notification every reconcile. Dismiss the moment the
    # fleet converges or the report is disabled (interval 0); the dismiss runs
    # unconditionally (the dispatcher no-ops it when no report is active) so a
    # stale pending PN that converged while the instance state was gone -- e.g.
    # an entry reload -- is cleared on the first reconcile after.
    pending_body = notification.render_report_body(rep, pending_only=True)
    has_pending = bool(pending_body)
    if _pending_publish_due(
        has_pending=has_pending,
        interval_hours=pending_report_interval_hours,
        last_publish=state.last_pending_publish_dt,
        now=now,
    ):
        await _dispatch_single(
            hass,
            prefix,
            "pending",
            instance_id,
            "Z-Wave Parameter Manager: pending configuration",
            pending_body,
            active=True,
        )
        state.last_pending_publish_dt = now
    elif not has_pending or pending_report_interval_hours <= 0:
        await _dispatch_single(
            hass,
            prefix,
            "pending",
            instance_id,
            "Z-Wave Parameter Manager: pending configuration",
            "",
            active=False,
        )
        state.last_pending_publish_dt = None

    # Unused-config report: configured policies / settings that landed on no
    # device (typos, mis-scoped selectors, stale concepts). Re-evaluated every
    # reconcile -- unlike the desired report it carries no live values, so its
    # body is stable and the dispatcher's content-dedup suppresses re-bubbling
    # while still self-correcting when the unused set changes (e.g. a node
    # joins that a previously-empty policy now matches). Dismissed when empty.
    unused_body = notification.render_unused_body(plan.unused)
    await _dispatch_single(
        hass,
        prefix,
        "unused",
        instance_id,
        "Z-Wave Parameter Manager: unused configuration",
        unused_body,
        active=bool(unused_body),
    )

    state.last_config_mtime = current_mtime
    state.last_reconcile_dt = now
    _persist(
        hass,
        state,
        now=now,
        current_mtime=current_mtime,
        trigger_id=trigger_id,
        extra={
            "devices": len(rep.devices),
            "writes_planned": len(plan.writes),
            "writes_issued": len(decision.writes),
            "pending": len(decision.pending),
            "converged": rep.converged_count,
            "pending_params": rep.pending_count,
            "plan_warnings": len(plan.warnings),
            "plan_errors": len(plan.errors),
            "unused": len(plan.unused),
            "pending_writes": _pending_summary(decision.pending),
        },
    )

    if debug_logging:
        _LOGGER.warning(
            "%s trigger=%s devices=%d planned=%d issued=%d "
            "pending=%d converged=%d",
            tag,
            trigger_id,
            len(reads),
            len(plan.writes),
            len(decision.writes),
            len(decision.pending),
            rep.converged_count,
        )


# --------------------------------------------------------
# Write dispatch + notification helpers
# --------------------------------------------------------


async def _dispatch_writes(
    hass: HomeAssistant, writes: tuple[PlannedWrite, ...]
) -> None:
    """Issue each planned write through the in-process zwave_js services.

    A whole Configuration-CC parameter goes through ``set_config_parameter``
    (which knows the device's value size / format); a partial / bitmask
    parameter (``property_key`` set) and the Wake Up interval go through
    ``set_value``, which addresses the exact value-id -- so a partial write
    never silently targets the whole parameter and then never converges.

    Fire-and-forget (``blocking=False``): a sleeping device's command sits
    in the add-on wake-up queue until it wakes, so we never block on it; the
    next reconcile confirms via convergence.
    """
    for write in writes:
        device_id = write.device.device_id
        if device_id is None:
            continue
        pid = write.id
        if (
            pid.command_class == zpm_logic.CommandClass.CONFIGURATION
            and pid.property_key is None
        ):
            await hass.services.async_call(
                "zwave_js",
                "set_config_parameter",
                {
                    "device_id": device_id,
                    "endpoint": 0,
                    "parameter": pid.property_,
                    "value": write.value,
                },
                blocking=False,
            )
            continue
        data: dict[str, Any] = {
            "device_id": device_id,
            "command_class": int(pid.command_class),
            "endpoint": 0,
            "property": pid.property_,
            "value": write.value,
        }
        if pid.property_key is not None:
            data["property_key"] = pid.property_key
        await hass.services.async_call(
            "zwave_js", "set_value", data, blocking=False
        )


async def _dispatch_single(
    hass: HomeAssistant,
    prefix: str,
    kind: str,
    instance_id: str,
    title: str,
    message: str,
    *,
    active: bool,
) -> None:
    """Create or dismiss one fixed-id notification category.

    Each ZPM category owns a single stable id, so the bare dispatcher
    (no sweep) toggles it independently of the others.
    """
    await process_persistent_notifications(
        hass,
        [
            PersistentNotification(
                active=active,
                notification_id=f"{prefix}{kind}",
                title=title,
                message=message,
                instance_id=instance_id,
            )
        ],
    )


def _issue_line(issue: PlanIssue) -> str:
    return (
        f"- `{md_escape(issue.device.name)}` / "
        f"`{issue.concept}`: {md_escape(issue.reason)}"
    )


def _pending_publish_due(
    *,
    has_pending: bool,
    interval_hours: int,
    last_publish: datetime | None,
    now: datetime,
) -> bool:
    """Whether to (re)publish the pending report this cycle.

    True when a parameter is pending, the report is enabled
    (``interval_hours`` > 0), and either nothing is currently published (so
    the first pending param publishes promptly) or the interval has elapsed
    since the last publish (the periodic refresh). A drifting wake estimate
    alone never satisfies this -- only the clock does.
    """
    if not has_pending or interval_hours <= 0:
        return False
    if last_publish is None:
        return True
    return now - last_publish >= timedelta(hours=interval_hours)


def _pending_summary(pending: dict[tuple[int, ParamId], int]) -> list[str]:
    """Human-readable pending entries for the diagnostic entity."""
    out: list[str] = []
    for (node_id, pid), value in pending.items():
        out.append(
            f"node {node_id} cc{pid.command_class}/{pid.property_}={value}"
        )
    return out


def _persist(
    hass: HomeAssistant,
    state: ZpmInstanceState,
    *,
    now: datetime,
    current_mtime: float,
    trigger_id: str,
    extra: dict[str, Any],
) -> None:
    attrs: dict[str, Any] = {
        "last_config_mtime": current_mtime,
        "last_trigger": trigger_id or "",
        "last_reconcile": (
            state.last_reconcile_dt.isoformat()
            if state.last_reconcile_dt is not None
            else ""
        ),
    }
    attrs.update(extra)
    update_instance_state(
        hass,
        service_tag=_SERVICE_TAG,
        instance_id=state.instance_id,
        last_run=now,
        runtime=(dt_util.now() - now).total_seconds(),
        extra_attributes=attrs,
    )


# --------------------------------------------------------
# Config file I/O (sync; runs in the executor)
# --------------------------------------------------------


def _resolve_config_path(hass: HomeAssistant, config_file_path: str) -> str:
    if os.path.isabs(config_file_path):
        return config_file_path
    return os.path.join(hass.config.config_dir, config_file_path)


def _info_path(hass: HomeAssistant) -> Path:
    """The shared driver-session record path under the config dir."""
    return Path(hass.config.config_dir) / driver_session.INFO_REL_PATH


def _pending_path(hass: HomeAssistant) -> Path:
    """The shared ZPM pending-store path under the config dir."""
    return Path(hass.config.config_dir) / pending_store.PENDING_REL_PATH


def _read_mtime(path: str) -> float:
    """Return mtime, or 0.0 if the file is missing."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


# --------------------------------------------------------
# Periodic timer + reconnect subscription
# --------------------------------------------------------


def _ensure_timer(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: ZpmInstanceState,
    interval_minutes: int,
) -> None:
    """Arm or re-arm the per-instance periodic reconcile timer."""
    if (
        state.cancel_timer is not None
        and state.armed_interval_minutes == interval_minutes
    ):
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


def _ensure_reconnect_subscription(
    hass: HomeAssistant, state: ZpmInstanceState
) -> None:
    """Subscribe (once) to the zwave_js driver-reconnect signal.

    A driver/add-on reconnect kicks a fresh reconcile promptly, rather than
    waiting for the periodic timer's next tick. The flush itself is detected
    by the driver-session record (the controller-statistics reset), so the
    kicked reconcile re-reads that record and re-issues every write flushed by
    the restart. The signal name needs ``home_id``, only available once the
    driver is up, so subscribe lazily per reconcile.
    """
    from homeassistant.helpers.dispatcher import async_dispatcher_connect

    from . import source

    if state.cancel_dispatcher is not None:
        return
    driver = source.get_driver(hass)
    if driver is None or driver.controller.home_id is None:
        return
    signal = f"zwave_js_{driver.controller.home_id}_connected_to_server"

    @callback  # type: ignore[untyped-decorator,unused-ignore]
    def _on_reconnect() -> None:
        # Kick a reconcile now for promptness; the flush decision itself is
        # made from the driver-session record inside that reconcile.
        entry = entry_for_domain(hass)
        if entry is None or not hass.services.has_service(
            "automation", "trigger"
        ):
            return
        entry.async_create_background_task(
            hass,
            hass.services.async_call(
                "automation",
                "trigger",
                {
                    "entity_id": state.instance_id,
                    "variables": {"trigger_id": "manual"},
                },
                blocking=False,
            ),
            name=f"{_SERVICE}_reconnect_{state.instance_id}",
        )

    state.cancel_dispatcher = async_dispatcher_connect(
        hass, signal, _on_reconnect
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


def _clear_dispatchers(hass: HomeAssistant) -> None:
    for state in _instances(hass).values():
        if state.cancel_dispatcher is not None:
            state.cancel_dispatcher()
            state.cancel_dispatcher = None


@callback  # type: ignore[untyped-decorator,unused-ignore]
def _on_reload(hass: HomeAssistant) -> None:
    _clear_dispatchers(hass)
    _MUTATORS.on_reload(hass)


@callback  # type: ignore[untyped-decorator,unused-ignore]
def _on_entity_remove(hass: HomeAssistant, entity_id: str) -> None:
    state = _instances(hass).get(entity_id)
    if state is not None and state.cancel_dispatcher is not None:
        state.cancel_dispatcher()
        state.cancel_dispatcher = None
    _MUTATORS.on_entity_remove(hass, entity_id)


_on_entity_rename = _MUTATORS.on_entity_rename


@callback  # type: ignore[untyped-decorator,unused-ignore]
def _on_teardown(hass: HomeAssistant) -> None:
    _clear_dispatchers(hass)
    _MUTATORS.on_teardown(hass)


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


async def async_register(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register ZPM's service + lifecycle via the shared helper."""
    await register_blueprint_handler(hass, entry, _SPEC)


async def async_unregister(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Tear down ZPM's service + lifecycle via the shared helper."""
    await unregister_blueprint_handler(hass, entry, _SPEC)


__all__ = [
    "BLUEPRINT_PATH",
    "ZpmInstanceState",
    "async_register",
    "async_unregister",
]
