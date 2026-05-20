# This is AI generated code
"""Lifecycle / setup-time helpers (function-body HA imports OK).

The "lifecycle" group of the three-flavour split
documented in ``helpers.py``'s shim docstring. These
helpers wire setup-time / registration-time HA machinery
and late-import HA modules inside their function bodies
to keep module import cheap.

Module-scope rule: module-scope ``homeassistant.*``
imports must be under ``if TYPE_CHECKING:``. Function-
body imports are unrestricted (the whole point of the
lifecycle group). The structural test
``test_helpers_lifecycle_module_scope_ha_imports_are_type_checking_only``
enforces this via AST walk.

Cross-flavour rule: this file may import from
``helpers_logic`` and ``helpers_runtime``.
"""

# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest-homeassistant-custom-component==0.13.331",
# ]
# ///

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .const import DOMAIN
from .helpers_logic import (
    _UNSUBS_KEY,
    BlueprintHandlerSpec,
    LifecycleMutators,
    PersistentNotification,
    parse_entity_registry_update,
    spec_bucket,
)
from .helpers_runtime import (
    dismiss_handler_crash_notification,
    emit_handler_crash_notification,
    kick_via_automation_trigger,
    process_persistent_notifications_with_sweep,
)

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant, ServiceCall

_LOGGER = logging.getLogger(__name__)


def all_integration_ids(hass: HomeAssistant) -> list[str]:
    """All distinct integration IDs across the entity registry.

    Used by the watchdog handlers to populate the truth set
    that include / exclude filters then narrow. Lives in the
    lifecycle flavour because it needs a function-body
    ``from homeassistant.helpers import entity_registry``
    -- HA removed the ``hass.helpers.*`` accessor surface,
    so module-imports are the only path to the registry.
    """
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    ent_reg = er.async_get(hass)
    integrations: set[str] = set()
    for entry in ent_reg.entities.values():
        if entry.platform:
            integrations.add(entry.platform)
    return sorted(integrations)


def integration_entity_ids(
    hass: HomeAssistant, integration_id: str
) -> list[str]:
    """Entity IDs registered by integration ``integration_id``.

    Walks the entity registry and returns every entry whose
    ``platform`` matches. ``platform`` is the integration /
    domain name HA writes onto each entry at registration,
    so grouping by it reliably partitions the registry by
    producing integration regardless of config-entry titles
    (which users can rename, and which differ between
    instances of multi-instance integrations).

    Lives alongside ``all_integration_ids`` because both
    pivot on the same registry walk and share the function-
    body HA import.
    """
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    ent_reg = er.async_get(hass)
    return [
        entry.entity_id
        for entry in ent_reg.entities.values()
        if entry.platform == integration_id
    ]


def file_editor_addon_ingress_url(hass: HomeAssistant) -> str:
    """Return the ingress URL prefix for the ``core_configurator`` add-on.

    The ``core_configurator`` add-on is HA's official "File
    editor" add-on (wraps ``danielperna84/hass-configurator``).
    Returns the per-installation ingress URL prefix
    (``/api/hassio_ingress/<uuid>/``) when the add-on is
    installed; returns the empty string otherwise.

    The ingress URL -- not the ``/core_configurator/`` panel
    URL -- is what callers want when emitting clickable
    notifications. HA's panel route consumes query strings
    on its way through the frontend router, so a link of
    the form ``/core_configurator/?loadfile=foo.yaml``
    routes the user to the panel without the configurator
    ever seeing ``loadfile``. The direct ingress URL
    (``/api/hassio_ingress/<uuid>/?loadfile=foo.yaml``)
    forwards the query string verbatim to the add-on's
    HTTP server, where the configurator's template
    substitutes it into ``init_loadfile`` and the JS
    actually opens the named file.

    The per-installation UUID rules out a hardcoded URL --
    the helper looks it up from the supervisor's addons-
    info table on every call. Returns an empty string on:

    - Container / Core HA installs (no Supervisor; the
      ``hassio`` integration isn't loaded).
    - Supervisor still warming up post-restart (the addons
      info table hasn't been populated yet).
    - The add-on isn't installed.
    - The add-on's ``ingress_url`` field is ``None``
      (older Supervisor versions or a misconfigured
      install).

    The check is cheap (``hass.data`` lookup) so handlers
    probe per-evaluation -- install / uninstall events
    propagate on the next scan without a reload.
    """
    from homeassistant.helpers.hassio import is_hassio  # noqa: PLC0415

    if not is_hassio(hass):
        return ""
    from homeassistant.components.hassio import (  # noqa: PLC0415
        get_addons_info,
    )

    addons = get_addons_info(hass)
    if not addons:
        return ""
    info = addons.get("core_configurator") or {}
    return info.get("ingress_url") or ""


def cv_ha_domain_list(value: object) -> list[str]:
    """Validate a list of HA integration / domain slugs.

    Coerces the input to a list (per ``cv.ensure_list``),
    then rejects any item that doesn't match HA's actual
    domain charset (``homeassistant.core.valid_domain``):
    lowercase letters / digits / underscores, no leading
    or trailing underscore, no double-underscores. Leading
    digits are allowed (real HA core integrations like
    ``3_day_blinds`` rely on this).

    Designed for use as a ``vol.Schema`` value.
    """
    import voluptuous as vol
    from homeassistant.core import valid_domain
    from homeassistant.helpers import config_validation as cv

    items = [str(i) for i in cv.ensure_list(value)]
    invalid = [i for i in items if not valid_domain(i)]
    if invalid:
        msg = (
            f"Invalid HA integration / domain id(s): "
            f"{', '.join(repr(i) for i in invalid)}. "
            "Each value must be lowercase letters, digits, "
            "and underscores, with no leading or trailing "
            "underscore and no double-underscore."
        )
        raise vol.Invalid(msg)
    return items


def discover_automations_using_blueprint(
    hass: HomeAssistant,
    blueprint_path: str,
) -> list[str]:
    """Return entity_ids of automations using ``blueprint_path``.

    Walks ``hass.data[DATA_COMPONENT].entities`` and
    matches ``BaseAutomationEntity.referenced_blueprint``
    (HA core's ``homeassistant/components/automation/__init__.py``).
    Returns an empty list when the automation component
    isn't loaded yet (early in HA startup).
    """
    from homeassistant.components.automation import (  # noqa: PLC0415
        DATA_COMPONENT,
    )

    component = hass.data.get(DATA_COMPONENT)
    if component is None:
        return []
    return [
        ent.entity_id
        for ent in component.entities
        if getattr(ent, "referenced_blueprint", None) == blueprint_path
    ]


async def recover_at_startup(
    hass: HomeAssistant,
    *,
    service_tag: str,
    blueprint_path: str,
    kick: Callable[[HomeAssistant, str], Awaitable[None]],
) -> None:
    """Discover, log, and kick every automation using ``blueprint_path``.

    Fires the per-port ``kick`` callable once per
    discovered automation entity_id. Standardises the
    "no automations discovered" / "kicking N for catch-up"
    INFO log lines so all subpackages surface the same
    diagnostic shape.
    """
    discovered = discover_automations_using_blueprint(hass, blueprint_path)
    if not discovered:
        _LOGGER.info(
            "[%s] no automations using %s discovered at startup",
            service_tag,
            blueprint_path,
        )
        return
    _LOGGER.info(
        "[%s] kicking %d discovered automations for catch-up",
        service_tag,
        len(discovered),
    )
    # Best-effort: a single bad automation entity must
    # not stop recovery for the rest of the discovered
    # set. Catch + log, then continue.
    for entity_id in discovered:
        try:
            await kick(hass, entity_id)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "[%s] catch-up kick for %s failed: %s",
                service_tag,
                entity_id,
                e,
            )


def schedule_periodic_with_jitter(
    hass: HomeAssistant,
    entry: Any,
    *,
    interval: timedelta,
    instance_id: str,
    action: Callable[[datetime], Awaitable[Any]],
) -> Callable[[], None]:
    """Schedule ``action`` every ``interval`` with a deterministic
    per-instance offset.

    Multiple instances sharing the same interval would
    otherwise all fire on the exact same wall-clock tick
    (HA boot, integration reload arms every per-instance
    timer at the same instant). The jitter spreads them
    across the interval window to avoid a thundering-herd
    on shared registries / file systems / external APIs.

    The offset is derived from a stable hash of
    ``instance_id`` (first 4 bytes of SHA-1, big-endian,
    mod the interval in seconds), so a given automation
    always lands on the same per-interval slot across
    restarts -- handy for log readers correlating across
    days. Mechanically:

    1. Schedule the first call via ``async_call_later``
       at ``now + jitter_seconds``.
    2. When that one-shot fires, arm
       ``async_track_time_interval`` for steady-state
       and run ``action`` once now.

    Returns a single unsubscribe callable that cancels
    whichever timer is currently active. Imported lazily
    to keep module import safe in non-HA test
    environments.

    ``action`` must be a coroutine function; it's invoked
    via ``entry.async_create_background_task`` so an entry
    unload mid-tick cancels the in-flight action rather than
    leaving it running detached against a torn-down service
    registration.
    """
    from homeassistant.core import callback  # noqa: PLC0415
    from homeassistant.helpers.event import (  # noqa: PLC0415
        async_call_later,
        async_track_time_interval,
    )

    interval_seconds = max(1, int(interval.total_seconds()))
    digest = hashlib.sha1(instance_id.encode("utf-8")).digest()
    jitter_seconds = int.from_bytes(digest[:4], "big") % interval_seconds

    # Single-slot mutable holder so the unsub closure can
    # see whichever timer is currently armed (initial
    # one-shot or steady-state interval).
    cancel_holder: dict[str, Callable[[], None] | None] = {"current": None}

    task_name = f"{DOMAIN}_periodic_tick_{instance_id}"

    @callback  # type: ignore[untyped-decorator,unused-ignore]
    def _fire_action(now: datetime) -> None:
        # Wrap so every tick (jittered first fire AND each
        # steady-state tick) goes through
        # ``entry.async_create_background_task``. Passing
        # ``action`` directly to ``async_track_time_interval``
        # would route subsequent ticks through HA's internal
        # ``hass.async_create_task``, leaving them detached
        # from entry unload.
        entry.async_create_background_task(hass, action(now), task_name)

    @callback  # type: ignore[untyped-decorator,unused-ignore]
    def _on_first_fire(now: datetime) -> None:
        # The one-shot fired and HA already removed it.
        # Arm the steady-state tracker before kicking off
        # the action so an early teardown still cancels
        # subsequent ticks.
        cancel_holder["current"] = async_track_time_interval(
            hass,
            _fire_action,
            interval,
        )
        _fire_action(now)

    cancel_holder["current"] = async_call_later(
        hass,
        jitter_seconds,
        _on_first_fire,
    )

    def _unsub() -> None:
        cur = cancel_holder["current"]
        if cur is not None:
            cur()
            cancel_holder["current"] = None

    return _unsub


def make_lifecycle_mutators(
    *,
    instances_getter: Callable[[HomeAssistant], dict[str, Any]],
    cancel_field: str,
    service_tag: str,
    logger: logging.Logger,
    reset_armed_interval_on_reload: bool = False,
) -> LifecycleMutators:
    """Build the four standard lifecycle mutator callbacks.

    Every blueprint handler keeps a per-instance state map
    keyed by automation entity_id and shares an
    almost-identical shape for the four mutator callbacks
    plumbed through ``BlueprintHandlerSpec``: cancel pending
    timers / wakeups on reload, drop tracked state on
    removal, move tracked state on rename, clear everything
    on teardown.

    ``cancel_field`` is the attribute name of the cancel-
    callable on each instance-state object (typically
    ``cancel_timer`` for periodic handlers,
    ``cancel_wakeup`` for one-shot handlers like TEC).
    Reading via ``getattr`` keeps this generic across the
    field-name variants without forcing a shared dataclass
    base.

    ``reset_armed_interval_on_reload`` clears
    ``armed_interval_minutes`` to 0 on reload; set ``True``
    for handlers whose ``_ensure_timer`` re-arm decision
    compares against this field (DW / EDW / RW / ZRM) and
    leave ``False`` for handlers with no such field
    (STSC / TEC).
    """
    from homeassistant.core import callback  # noqa: PLC0415

    @callback  # type: ignore[untyped-decorator,unused-ignore]
    def _on_reload(hass: HomeAssistant) -> None:
        for s in list(instances_getter(hass).values()):
            cancel = getattr(s, cancel_field, None)
            if cancel is not None:
                cancel()
                setattr(s, cancel_field, None)
                if reset_armed_interval_on_reload:
                    s.armed_interval_minutes = 0

    @callback  # type: ignore[untyped-decorator,unused-ignore]
    def _on_entity_remove(hass: HomeAssistant, entity_id: str) -> None:
        s = instances_getter(hass).pop(entity_id, None)
        if s is None:
            return
        cancel = getattr(s, cancel_field, None)
        if cancel is not None:
            cancel()
            logger.info(
                "[%s] dropped %s (automation removed)",
                service_tag,
                entity_id,
            )

    @callback  # type: ignore[untyped-decorator,unused-ignore]
    def _on_entity_rename(
        hass: HomeAssistant,
        old_id: str,
        new_id: str,
    ) -> None:
        s = instances_getter(hass).pop(old_id, None)
        if s is not None:
            s.instance_id = new_id
            instances_getter(hass)[new_id] = s

    @callback  # type: ignore[untyped-decorator,unused-ignore]
    def _on_teardown(hass: HomeAssistant) -> None:
        for s in list(instances_getter(hass).values()):
            cancel = getattr(s, cancel_field, None)
            if cancel is not None:
                cancel()
        instances_getter(hass).clear()

    return LifecycleMutators(
        on_reload=_on_reload,
        on_entity_remove=_on_entity_remove,
        on_entity_rename=_on_entity_rename,
        on_teardown=_on_teardown,
    )


_CAP_SUMMARY_SUFFIX = "cap_summary"


def _flatten_repair_data(
    service_name: str,
    service_data: dict[str, Any],
) -> dict[str, Any]:
    """Build the ``data`` dict for a Repairs issue.

    HA's issue registry persists ``data`` to ``.storage`` via JSON
    round-trip; nested dicts and non-primitive values fail silently
    or corrupt at restore. ``service_name`` names the service the
    fix flow dispatches to; each ``service_data`` field is encoded
    as ``service_data_<key>``, which ``async_step_confirm`` rebuilds
    into the inverse.
    """
    out: dict[str, Any] = {"service_name": service_name}
    for k, v in service_data.items():
        out[f"service_data_{k}"] = v
    return out


async def process_repairs_with_sweep(
    hass: HomeAssistant,
    notifications: list[PersistentNotification],
    *,
    sweep_prefix: str,
    create_repairs: bool,
    repair_cap: int = 0,
    keep_pattern: str | None = None,
) -> set[str]:
    """Dispatch a per-instance batch routing repairs vs notifications.

    Each spec is one of:

    - ``active=True, repair_callback=<tuple>`` -- repair candidate.
      Routed to the issue registry when ``create_repairs=True``;
      dropped when ``create_repairs=False`` (the logic instead
      builds the finding as a ``repair_callback=None`` spec, so it
      still surfaces once -- as a persistent notification).
    - ``active=True, repair_callback=None`` -- always a
      notification
    - ``active=False`` -- dismiss spec for either backend.

    Sweep semantics match
    ``process_persistent_notifications_with_sweep``: any prior-run
    artifact (notification or issue) under ``sweep_prefix`` not in
    the current batch is removed from its respective backend.

    ``repair_cap`` of 0 disables the cap. Above zero, the first N
    repair specs surface as issues; the rest are summarised by a
    single cap-summary notification under the per-instance
    prefix. The cap-summary slot is always dispatched (active
    when over cap, inactive otherwise).

    Returns the set of ``notification_id``\\ s for active repair
    specs that actually landed in the issue registry (post-cap,
    post-toggle, dismiss specs excluded). Callers use this to
    filter any per-repair side data they keep on the instance
    state -- a payload for a repair that got suppressed by the
    cap shouldn't be reachable from a service-call dispatch even
    though the user can't click the (non-existent) issue.
    """
    notif_specs: list[PersistentNotification] = []
    repair_specs: list[PersistentNotification] = []
    for spec in notifications:
        if spec.repair_callback is None:
            notif_specs.append(spec)
        elif create_repairs:
            repair_specs.append(spec)
        # When create_repairs=False, repair-marked specs drop
        # entirely -- the handler emits the per-device summary
        # notification alongside (which still routes here as a
        # repair_callback=None spec), so the user sees the
        # finding once via the original notification surface.

    # Deterministic cap: sort by notification_id (the
    # natural key for a repair spec -- its title and
    # message are translation-rendered and intentionally
    # empty here, so notification_id is the only
    # caller-stable key) so the visible / suppressed split
    # is reproducible across runs. Matches the notification-
    # side sort that ``prepare_notifications`` performs.
    repair_specs.sort(key=lambda s: s.notification_id)

    if create_repairs:
        # The cap-summary inherits the batch's instance_id so
        # the notification dispatcher prepends the standard
        # ``Automation: [name](edit-link)`` header. The batch
        # is per-instance by construction, so any spec's
        # instance_id is the right one to use.
        cap_instance_id = next(
            (s.instance_id for s in notifications if s.instance_id),
            None,
        )
        cap_summary_id = f"{sweep_prefix}{_CAP_SUMMARY_SUFFIX}"
        if repair_cap > 0 and len(repair_specs) > repair_cap:
            suppressed = repair_specs[repair_cap:]
            repair_specs = repair_specs[:repair_cap]
            count = len(suppressed)
            notif_specs.append(
                PersistentNotification(
                    active=True,
                    notification_id=cap_summary_id,
                    title=(
                        f"{count} additional repairable findings suppressed"
                    ),
                    message=(
                        f"The per-run repair cap is `{repair_cap}`. "
                        "Raise the `max_repairs` blueprint input or "
                        "fix the visible repairs first to surface "
                        "more."
                    ),
                    instance_id=cap_instance_id,
                ),
            )
        else:
            notif_specs.append(
                PersistentNotification(
                    active=False,
                    notification_id=cap_summary_id,
                    title="",
                    message="",
                    instance_id=cap_instance_id,
                ),
            )

    await _dispatch_repairs_with_sweep(
        hass,
        repair_specs,
        sweep_prefix=sweep_prefix,
    )
    await process_persistent_notifications_with_sweep(
        hass,
        notif_specs,
        sweep_prefix=sweep_prefix,
        keep_pattern=keep_pattern,
    )
    return {s.notification_id for s in repair_specs if s.active}


async def _dispatch_repairs_with_sweep(
    hass: HomeAssistant,
    specs: list[PersistentNotification],
    *,
    sweep_prefix: str,
) -> None:
    """Create / dismiss issues + sweep prefix-matching orphans.

    Per-scan blind re-issuance against the issue registry is
    intentionally cheap: HA's ``ir.async_create_issue`` calls
    ``IssueRegistry.async_get_or_create``, which builds the
    replacement entry and only fires the registry-updated
    event + schedules a save when ``replacement != issue``
    (``homeassistant/helpers/issue_registry.py`` -- the
    ``# Only fire is something changed`` branch). HA's
    ``async_delete`` similarly returns early when the
    ``(domain, issue_id)`` isn't present. So repeat calls
    with byte-identical state are end-to-end no-ops -- no
    bus event, no UI re-render, no Repairs-panel churn --
    and this dispatcher doesn't need a content-equality
    guard of its own. That's the opposite of HA's
    ``persistent_notification.create``, which re-publishes
    unconditionally; the notification-side dispatcher in
    ``process_persistent_notifications`` carries its own
    skip-when-identical guard for that reason.
    """
    from homeassistant.helpers import (  # noqa: PLC0415
        issue_registry as ir,
    )

    active_ids: set[str] = set()
    for spec in specs:
        if not spec.active:
            ir.async_delete_issue(hass, DOMAIN, spec.notification_id)
            continue

        assert spec.repair_callback is not None
        fix = spec.repair_callback
        active_ids.add(spec.notification_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            spec.notification_id,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=spec.translation_key,
            translation_placeholders=spec.translation_placeholders or {},
            data=_flatten_repair_data(
                fix.service_name,
                {"notification_id": fix.notification_id},
            ),
        )

    registry = ir.async_get(hass)
    for issue in list(registry.issues.values()):
        if issue.domain != DOMAIN:
            continue
        if not issue.issue_id.startswith(sweep_prefix):
            continue
        if issue.issue_id in active_ids:
            continue
        ir.async_delete_issue(hass, DOMAIN, issue.issue_id)


async def register_blueprint_handler(
    hass: HomeAssistant,
    entry: Any,
    spec: BlueprintHandlerSpec,
) -> None:
    """Register the service + every lifecycle hook the spec opted into.

    Idempotent under config-entry reload -- existing
    service registration is removed first; existing
    bus subscriptions are unsubscribed before
    re-subscribing.
    """
    from homeassistant.components.automation import (  # noqa: PLC0415
        EVENT_AUTOMATION_RELOADED,
    )
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED  # noqa: PLC0415
    from homeassistant.core import callback  # noqa: PLC0415
    from homeassistant.helpers import (  # noqa: PLC0415
        entity_registry as er,
    )

    bucket = spec_bucket(entry, spec.service)

    # --- Service registration (always) ---
    if hass.services.has_service(DOMAIN, spec.service):
        hass.services.async_remove(DOMAIN, spec.service)

    async def _service_wrapper(call: ServiceCall) -> Any:
        # ``getattr`` rather than ``call.data`` directly so
        # that synthetic test invocations passing a bare
        # placeholder (no ``.data`` attribute) still flow
        # through the wrap correctly. Real ``ServiceCall``
        # objects always carry a ``data`` mapping; missing
        # / ``None`` lands in the per-service
        # ``__unknown__crash`` slot.
        raw = getattr(call, "data", None)
        raw_data = dict(raw) if raw is not None else {}
        try:
            result = await spec.service_handler(hass, call)
        except Exception as exc:
            # Intentionally broad: anything the handler
            # raised that wasn't already caught + surfaced
            # by its own argparse / state-write path is a
            # crash from HA's perspective and would
            # otherwise leave the user with only a log
            # entry as evidence. ``asyncio.CancelledError``
            # inherits from ``BaseException`` since
            # Python 3.8 and is intentionally NOT caught
            # here. After emitting the PN, the original
            # exception is re-raised so HA's own
            # error-handling fires too (automation page
            # indicator, logbook entry, ERROR-level
            # traceback in the log).
            try:
                await emit_handler_crash_notification(
                    hass,
                    service=spec.service,
                    service_tag=spec.service_tag,
                    raw_data=raw_data,
                    exc=exc,
                )
            except Exception:  # noqa: BLE001
                # The PN dispatch itself failed (HA
                # shutting down, services unavailable,
                # ...). Log it so the failure to surface
                # the underlying crash is itself visible,
                # then proceed -- don't shadow the real
                # exception with the notification dispatch
                # failure.
                _LOGGER.exception(
                    "Failed to emit handler-crash notification for %s",
                    spec.service,
                )
            raise
        try:
            # Auto-clear any prior ``__crash`` PN now that
            # the handler ran cleanly. The dismiss is a
            # no-op when no crash PN is active (handled
            # inside ``process_persistent_notifications``),
            # so the steady-state success path costs one
            # dict lookup. Wrapped in its own try / except
            # so a dismiss-time failure can't break a
            # successful handler invocation -- the worst
            # case is a stale ``__crash`` PN that the
            # next clean run gets another chance to clear.
            await dismiss_handler_crash_notification(
                hass,
                service=spec.service,
                raw_data=raw_data,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Failed to dismiss prior handler-crash notification for %s",
                spec.service,
            )
        return result

    # Per-spec ``supports_response`` plumbing: handlers that
    # hand a ``ServiceResponse`` mapping back to the calling
    # blueprint (so the blueprint can run a user-supplied
    # action step against it) opt in by setting
    # ``supports_response`` on their ``BlueprintHandlerSpec``;
    # everyone else passes ``None`` and the dispatcher
    # registers without the kwarg, leaving HA's default
    # (no response) in place.
    if spec.supports_response is not None:
        hass.services.async_register(
            DOMAIN,
            spec.service,
            _service_wrapper,
            supports_response=spec.supports_response,
        )
    else:
        hass.services.async_register(DOMAIN, spec.service, _service_wrapper)

    # Idempotent re-register: tear down every prior unsub
    # before re-subscribing so listener counts stay 1.
    unsubs: list[Callable[[], None]] = bucket[_UNSUBS_KEY]
    for prior in unsubs:
        prior()
    unsubs.clear()

    # Local-capture the optional hooks so closures see
    # the narrowed (non-None) type and so mypy doesn't
    # have to track narrowing through closure boundaries.
    on_reload = spec.on_reload
    on_entity_remove = spec.on_entity_remove
    on_entity_rename = spec.on_entity_rename
    # The ``kick`` action is derived from ``spec.kick_variables``
    # if set: every per-port kick is just an
    # ``automation.trigger`` with a flat-variables payload, so
    # the spec carries the payload and the dispatcher builds
    # the action. Per-handler ``_async_kick_for_recovery``
    # wrappers have all been deleted.
    kick: Callable[[HomeAssistant, str], Awaitable[None]] | None
    if spec.kick_variables is not None:
        kick_variables = spec.kick_variables

        async def _kick(hass: HomeAssistant, entity_id: str) -> None:
            await kick_via_automation_trigger(hass, entity_id, kick_variables)

        kick = _kick
    else:
        kick = None

    # --- Reload listener (if any per-reload behaviour
    # is configured) ---
    if on_reload is not None or kick is not None:
        reload_recover_task_name = f"{DOMAIN}_{spec.service}_reload_recover"

        @callback  # type: ignore[untyped-decorator,unused-ignore]
        def _reload_listener(_event: Event) -> None:
            if on_reload is not None:
                on_reload(hass)
            if kick is not None:
                # Entry-scoped: matches the startup-recovery
                # path below. Without this, an entry unload
                # racing the reload would leave the recover
                # task running detached against a torn-down
                # service registration.
                entry.async_create_background_task(
                    hass,
                    recover_at_startup(
                        hass,
                        service_tag=spec.service_tag,
                        blueprint_path=spec.blueprint_path,
                        kick=kick,
                    ),
                    reload_recover_task_name,
                )

        unsubs.append(
            hass.bus.async_listen(
                EVENT_AUTOMATION_RELOADED,
                _reload_listener,
            ),
        )

    # --- Entity-registry listener (if either remove or
    # rename hook is set) ---
    if on_entity_remove is not None or on_entity_rename is not None:

        @callback  # type: ignore[untyped-decorator,unused-ignore]
        def _er_listener(event: Event) -> None:
            parsed = parse_entity_registry_update(event.data)
            if parsed is None:
                return
            action, old_id, new_id = parsed
            if action == "remove" and on_entity_remove is not None:
                on_entity_remove(hass, old_id)
            elif (
                action == "update"
                and old_id != new_id
                and on_entity_rename is not None
            ):
                on_entity_rename(hass, old_id, new_id)

        # HA types ``async_listen`` for ``EVENT_ENTITY_REGISTRY_UPDATED``
        # against a specific TypedDict union (Create / Remove / Update
        # variants); this listener accepts the generic ``Event`` and
        # narrows via ``parse_entity_registry_update``. The runtime
        # contract -- ``event.data`` carries the registry-update keys
        # -- holds; the type-narrowness is the only thing mypy
        # --strict has to flag.
        unsubs.append(
            hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED,
                _er_listener,  # type: ignore[arg-type,unused-ignore]
            ),
        )

    # --- Restart recovery (if kick is configured) ---
    if kick is not None:
        # Both branches schedule via
        # ``entry.async_create_background_task`` rather than
        # ``hass.async_create_task`` so the recovery work is
        # entry-scoped: if the config entry unloads (e.g.
        # the user disables the integration) while the task
        # is still queued or mid-flight, HA cancels it
        # automatically. Without this, an unload that races
        # the recover task would leave kicks firing into a
        # detached service registration.
        recover_task_name = f"{DOMAIN}_{spec.service}_recover_at_startup"
        if hass.is_running:
            entry.async_create_background_task(
                hass,
                recover_at_startup(
                    hass,
                    service_tag=spec.service_tag,
                    blueprint_path=spec.blueprint_path,
                    kick=kick,
                ),
                recover_task_name,
            )
        else:
            # ``async_listen_once`` returns an unsubscribe
            # callable AND auto-detaches the listener when
            # the event fires. If the listener fires and we
            # later call the stored unsub (e.g. on
            # integration unload), HA logs ``Unable to
            # remove unknown job listener`` at ERROR level.
            # Drop our bookkeeping handle synchronously
            # inside the dispatch so any concurrent
            # ``unregister_blueprint_handler`` won't see it.
            #
            # The wrapper is ``@callback`` (sync) so the
            # ``unsubs.remove`` runs in the same synchronous
            # block as HA's listener detach inside
            # ``Bus.async_fire``; the background-task
            # creation then schedules the actual recovery
            # work. If the wrapper were ``async def``
            # instead, the recovery would be scheduled as a
            # separate task and there'd be a (tiny but real)
            # race window where unregister could fire and
            # call the stale unsub before our async body
            # removed it.
            once_unsub: Callable[[], None] | None = None

            @callback  # type: ignore[untyped-decorator,unused-ignore]
            def _on_started_sync(_event: Event) -> None:
                if once_unsub is not None and once_unsub in unsubs:
                    unsubs.remove(once_unsub)
                entry.async_create_background_task(
                    hass,
                    recover_at_startup(
                        hass,
                        service_tag=spec.service_tag,
                        blueprint_path=spec.blueprint_path,
                        kick=kick,
                    ),
                    recover_task_name,
                )

            once_unsub = hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED,
                _on_started_sync,
            )
            # Stored so unregister can detach the listener
            # if the entry unloads before HA finishes
            # starting (i.e. before the once-listener fires
            # and removes itself).
            unsubs.append(once_unsub)

    _LOGGER.info(
        "%s [%s]: service %s.%s registered (blueprint=%s)",
        spec.service_name,
        spec.service_tag,
        DOMAIN,
        spec.service,
        spec.blueprint_path,
    )


__all__ = [
    "all_integration_ids",
    "cv_ha_domain_list",
    "file_editor_addon_ingress_url",
    "integration_entity_ids",
    "make_lifecycle_mutators",
    "process_repairs_with_sweep",
    "register_blueprint_handler",
    "schedule_periodic_with_jitter",
]
