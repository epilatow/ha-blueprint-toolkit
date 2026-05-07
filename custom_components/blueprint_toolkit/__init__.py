# This is AI generated code
"""blueprint_toolkit integration entry points.

Wraps the reconciler (no HA dependencies; safe to import
+ call outside the HA process) and sync installer modules
in the HA async lifecycle: ``async_setup_entry``
plans + applies on every startup, ``async_remove_entry``
removes everything previously installed when the user
uninstalls the integration.

Module-level imports stay HA-free so the reconciler /
installer modules remain importable from non-HA test
environments. HA-specific imports happen inside the entry
point functions, and type annotations live behind
``TYPE_CHECKING`` so they evaluate lazily under
``from __future__ import annotations``.
"""

# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pytest-homeassistant-custom-component==0.13.331",
# ]
# ///

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import installer, reconciler
from .const import DOMAIN, OPTION_CLI_SYMLINK_DIR

# Repairs issue IDs are duplicated here (the source-of-
# truth lives in repairs.py) rather than imported, so this
# module's import graph stays HA-free for the unit tests
# that import via the package path.
_ISSUE_INSTALL_CONFLICTS = "install_conflicts"
_ISSUE_INSTALL_FAILURE = "install_failure"

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


@dataclass
class IntegrationData:
    """Per-config-entry runtime state.

    Lives at ``entry.runtime_data``; HA auto-clears the
    attribute on entry unload, but our explicit
    ``async_unload_entry`` still walks ``handlers`` to
    cancel pending wakeups + unsubscribe bus listeners
    before that happens. ``handlers[<service>]`` is the
    per-port bucket the shared lifecycle helpers in
    ``helpers.py`` populate.

    Cross-reload state (the Repairs-flow handoff for
    force-confirmed destinations) lives separately in
    ``hass.data[DOMAIN]`` because it must survive the
    unload between Repairs flow completion and the
    triggered config-entry reload.
    """

    handlers: dict[str, dict[str, Any]] = field(default_factory=dict)


_LOGGER = logging.getLogger(__name__)

# Files under bundled/ ship with the integration; HA reads
# manifest.json to discover them. We resolve our own
# location rather than hass.config.path so that running
# under unusual config-dir setups still works.
_BUNDLED_ROOT = Path(__file__).parent / "bundled"


def _coerce_cli_symlink_dir(raw: object) -> Path | None:
    """Return a Path for the option, or None when unset/empty."""
    if not raw:
        return None
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    return Path(raw)


async def _fire_reload_services(
    hass: HomeAssistant,
    *,
    automation: bool,
) -> None:
    if automation and hass.services.has_service(
        "automation",
        "reload",
    ):
        await hass.services.async_call(
            "automation",
            "reload",
            blocking=True,
        )


def _register_docs_static_route(hass: HomeAssistant) -> None:
    """Serve rendered docs at /local/blueprint_toolkit/docs/.

    HA's default ``/local/`` handler refuses to follow
    symlinks whose targets escape ``/config/www/``, and is
    only wired up at startup if ``/config/www/`` already
    exists. We sidestep both by registering our own
    aiohttp static route, pointing directly at the bundled
    docs directory inside the integration. Doc links work
    for HACS-installed users; dev-install users (who don't
    load this integration) see broken /local/ doc links --
    a documented dev-install limitation.
    """
    docs_dir = _BUNDLED_ROOT / "www" / "blueprint_toolkit" / "docs"
    if not docs_dir.is_dir():
        _LOGGER.warning(
            "docs directory missing under bundled payload: %s",
            docs_dir,
        )
        return
    hass.http.app.router.add_static(
        prefix="/local/blueprint_toolkit/docs",
        path=str(docs_dir),
        show_index=False,
    )


_FIX_SERVICES = (
    "fix_edw_entity_id_drift",
    "fix_edw_entity_name_drift",
    "fix_dw_disabled_diagnostic_entity",
)


def _entity_excluded_anywhere(hass: HomeAssistant, entity_id: str) -> bool:
    """True when any active EDW / DW instance excludes ``entity_id``.

    Walks the per-instance state on the integration's config-
    entry bucket. A repair issue can outlive its underlying
    finding when the user adds an exclusion between the scan
    that created the issue and the click on Submit; this guard
    lets the fix service surface the conflict in the Repairs
    UI rather than mutating an entity the user told the
    watchdog to ignore.
    """
    from homeassistant.helpers import (  # noqa: PLC0415
        config_validation as cv,
    )

    from .helpers import matches_pattern  # noqa: PLC0415

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return False
    bucket = entries[0].runtime_data.handlers if entries[0].runtime_data else {}
    for service_key in ("entity_defaults_watchdog", "device_watchdog"):
        instances = bucket.get(service_key, {}).get("instances", {})
        for inst in instances.values():
            excluded = list(getattr(inst, "excluded_entities", []) or [])
            if entity_id in cv.ensure_list(excluded):
                return True
            regex = getattr(inst, "excluded_entity_id_regex", "") or ""
            if regex and matches_pattern(entity_id, regex):
                return True
    return False


def _register_fix_services(hass: HomeAssistant) -> None:
    """Register the per-finding repair services.

    Three services back the WatchdogFixFlow's Submit step:

    - ``fix_edw_entity_id_drift`` -- ``er.async_update_entity(entity_id,
      new_entity_id=...)``.
    - ``fix_edw_entity_name_drift`` -- ``er.async_update_entity(entity_id,
      name=...)``.
    - ``fix_dw_disabled_diagnostic_entity`` -- ``er.async_update_entity(
      entity_id, disabled_by=None)``.

    Each takes a single-entity payload (no bulk variants) and is
    registered idempotently -- ``hass.services.has_service`` guards
    re-registration on options-driven entry reload. Schemas live
    inline because the surface is small and the fields are
    standard cv types.

    Each service guards on ``_entity_excluded_anywhere`` so a
    repair issue created before the user added the entity to an
    exclusion list raises ``HomeAssistantError`` rather than
    mutating the entity behind the user's back.
    """
    import voluptuous as vol  # noqa: PLC0415
    from homeassistant.exceptions import (  # noqa: PLC0415
        HomeAssistantError,
    )
    from homeassistant.helpers import (  # noqa: PLC0415
        config_validation as cv,
    )
    from homeassistant.helpers import (  # noqa: PLC0415
        entity_registry as er,
    )

    def _check_excluded(entity_id: str) -> None:
        if _entity_excluded_anywhere(hass, entity_id):
            msg = (
                f"`{entity_id}` is excluded by an active watchdog instance. "
                "Remove the exclusion (or wait for the next scan to clear "
                "this repair) before applying the fix."
            )
            raise HomeAssistantError(msg)

    async def _fix_edw_entity_id_drift(call: Any) -> None:
        _check_excluded(call.data["entity_id"])
        ent_reg = er.async_get(hass)
        ent_reg.async_update_entity(
            call.data["entity_id"],
            new_entity_id=call.data["new_entity_id"],
        )

    async def _fix_edw_entity_name_drift(call: Any) -> None:
        _check_excluded(call.data["entity_id"])
        ent_reg = er.async_get(hass)
        ent_reg.async_update_entity(
            call.data["entity_id"],
            name=call.data["name"],
        )

    async def _fix_dw_disabled_diagnostic_entity(call: Any) -> None:
        _check_excluded(call.data["entity_id"])
        ent_reg = er.async_get(hass)
        ent_reg.async_update_entity(
            call.data["entity_id"],
            disabled_by=None,
        )

    if not hass.services.has_service(DOMAIN, "fix_edw_entity_id_drift"):
        hass.services.async_register(
            DOMAIN,
            "fix_edw_entity_id_drift",
            _fix_edw_entity_id_drift,
            schema=vol.Schema(
                {
                    vol.Required("entity_id"): cv.entity_id,
                    vol.Required("new_entity_id"): cv.entity_id,
                },
            ),
        )
    if not hass.services.has_service(DOMAIN, "fix_edw_entity_name_drift"):
        hass.services.async_register(
            DOMAIN,
            "fix_edw_entity_name_drift",
            _fix_edw_entity_name_drift,
            schema=vol.Schema(
                {
                    vol.Required("entity_id"): cv.entity_id,
                    vol.Required("name"): vol.Coerce(str),
                },
            ),
        )
    if not hass.services.has_service(
        DOMAIN,
        "fix_dw_disabled_diagnostic_entity",
    ):
        hass.services.async_register(
            DOMAIN,
            "fix_dw_disabled_diagnostic_entity",
            _fix_dw_disabled_diagnostic_entity,
            schema=vol.Schema(
                {
                    vol.Required("entity_id"): cv.entity_id,
                },
            ),
        )


async def _async_options_updated(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Re-run setup when the options flow changes anything.

    Without this listener HA quietly persists the new
    options and the reconciler is not re-run until next HA
    restart. With it, changing ``cli_symlink_dir`` (or any
    future option) takes effect immediately.
    """
    await hass.config_entries.async_reload(entry.entry_id)


def _surface_conflicts(
    hass: HomeAssistant,
    entry: ConfigEntry,
    conflicts: tuple[reconciler.Conflict, ...],
) -> None:
    from homeassistant.helpers import issue_registry as ir

    if not conflicts:
        ir.async_delete_issue(hass, DOMAIN, _ISSUE_INSTALL_CONFLICTS)
        return
    serialised = [
        {
            "destination": str(c.destination),
            "kind": c.kind,
            "details": c.details,
        }
        for c in conflicts
    ]
    # HA's IssueData TypedDict (from homeassistant.helpers.issue_registry)
    # constrains values to JSON-primitive (str / int / float / None). The
    # repairs flow (repairs.py + test_repairs.py) reads the nested lists
    # back via ``data["conflicts"]`` / ``data["conflict_destinations"]``;
    # HA's frontend round-trips JSON correctly for the nested shapes in
    # practice (the registry stores `data` as JSON), so the narrower
    # IssueData typing is conservative for our use. The ignore is paired
    # with ``unused-ignore`` so a stricter HA stub release that widens
    # IssueData doesn't break the build.
    ir.async_create_issue(
        hass,
        DOMAIN,
        _ISSUE_INSTALL_CONFLICTS,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=_ISSUE_INSTALL_CONFLICTS,
        data={
            "entry_id": entry.entry_id,
            "conflicts": serialised,  # type: ignore[dict-item,unused-ignore]
            "conflict_destinations": [  # type: ignore[dict-item,unused-ignore]
                str(c.destination) for c in conflicts
            ],
        },
    )


def _surface_failure(
    hass: HomeAssistant,
    entry: ConfigEntry,
    errors: list[str],
) -> None:
    from homeassistant.helpers import issue_registry as ir

    if not errors:
        ir.async_delete_issue(hass, DOMAIN, _ISSUE_INSTALL_FAILURE)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        _ISSUE_INSTALL_FAILURE,
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=_ISSUE_INSTALL_FAILURE,
        data={
            "entry_id": entry.entry_id,
            "errors": list(errors),  # type: ignore[dict-item,unused-ignore]
        },
    )


def _consume_pending_force_destinations(
    hass: HomeAssistant,
) -> frozenset[Path]:
    """Pop and return any force_destinations the Repairs flow stashed.

    The Repairs ``InstallConflictsFlow`` writes the
    user-confirmed destinations into ``hass.data[DOMAIN]``
    and triggers an integration reload; this call (which
    runs inside the next ``async_setup_entry``) consumes
    them so they don't leak into a subsequent reconcile.
    """
    bucket = hass.data.get(DOMAIN, {})
    raw = bucket.pop("pending_force_destinations", None)
    if not raw:
        return frozenset()
    return frozenset(Path(p) for p in raw)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Plan + apply the bundled payload's symlinks."""
    # Initialise per-entry runtime state. Subpackage
    # handler buckets land under ``entry.runtime_data.handlers``
    # via the shared lifecycle helpers in ``helpers.py``.
    entry.runtime_data = IntegrationData()
    config_root = Path(hass.config.config_dir)
    cli_symlink_dir = _coerce_cli_symlink_dir(
        entry.options.get(OPTION_CLI_SYMLINK_DIR),
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    force_destinations = _consume_pending_force_destinations(hass)

    plan = await hass.async_add_executor_job(
        functools.partial(
            reconciler.plan,
            bundled_root=_BUNDLED_ROOT,
            config_root=config_root,
            cli_symlink_dir=cli_symlink_dir,
            force_destinations=force_destinations,
        ),
    )

    result = await hass.async_add_executor_job(installer.apply, plan)

    if result.errors:
        for err in result.errors:
            _LOGGER.error("install error: %s", err)
    if result.conflicts:
        for c in result.conflicts:
            _LOGGER.warning(
                "install conflict at %s: %s %s",
                c.destination,
                c.kind,
                c.details,
            )

    _surface_conflicts(hass, entry, plan.conflicts)
    _surface_failure(hass, entry, result.errors)

    # Re-render blueprint-backed automation actions when
    # the bundled blueprint YAML changed, so HA picks up
    # any input renames / additions on the next service
    # call. Skipped when ``result.changed`` is False --
    # re-rendering automations is wasted work when nothing
    # bundled actually changed.
    await _fire_reload_services(hass, automation=result.changed)

    _register_docs_static_route(hass)

    # Per-port service handlers. Lazy-imported because each
    # handler module pulls in ``voluptuous`` and
    # ``homeassistant`` at module scope.
    from .device_watchdog import handler as dw_handler
    from .entity_defaults_watchdog import handler as edw_handler
    from .reference_watchdog import handler as rw_handler
    from .sensor_threshold_switch_controller import handler as stsc_handler
    from .trigger_entity_controller import handler as tec_handler
    from .zwave_route_manager import handler as zrm_handler

    await tec_handler.async_register(hass, entry)
    await zrm_handler.async_register(hass, entry)
    await rw_handler.async_register(hass, entry)
    await edw_handler.async_register(hass, entry)
    await dw_handler.async_register(hass, entry)
    await stsc_handler.async_register(hass, entry)

    _register_fix_services(hass)

    # Conflicts surface to the user via Repairs rather
    # than by failing the setup. Real install errors raise
    # an OSError inside the executor job which propagates
    # up and HA marks the integration as setup-failed.
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload the config entry. No filesystem side effects.

    Tears down each per-port handler so a reload (e.g.
    after ``_async_options_updated`` fires from an
    options-flow save) doesn't leak service
    registrations, bus listeners, or pending wakeups /
    timers.
    """
    from .device_watchdog import handler as dw_handler
    from .entity_defaults_watchdog import handler as edw_handler
    from .reference_watchdog import handler as rw_handler
    from .sensor_threshold_switch_controller import handler as stsc_handler
    from .trigger_entity_controller import handler as tec_handler
    from .zwave_route_manager import handler as zrm_handler

    await tec_handler.async_unregister(hass, entry)
    await zrm_handler.async_unregister(hass, entry)
    await rw_handler.async_unregister(hass, entry)
    await edw_handler.async_unregister(hass, entry)
    await dw_handler.async_unregister(hass, entry)
    await stsc_handler.async_unregister(hass, entry)
    for service in _FIX_SERVICES:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
    return True


async def async_remove_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove the config entry, wiping every ours-symlink we own."""
    config_root = Path(hass.config.config_dir)
    cli_symlink_dir = _coerce_cli_symlink_dir(
        entry.options.get(OPTION_CLI_SYMLINK_DIR),
    )
    ours = await hass.async_add_executor_job(
        functools.partial(
            reconciler.discover_ours_destinations,
            config_root,
            cli_symlink_dir,
        ),
    )
    if not ours:
        return

    actions = tuple(
        reconciler.Action(
            kind=reconciler.ActionKind.REMOVE,
            destination=dest,
            target=None,
        )
        for dest in sorted(ours)
    )
    plan = reconciler.ReconcilePlan(actions=actions, conflicts=())
    await hass.async_add_executor_job(installer.apply, plan)
    await _fire_reload_services(hass, automation=True)
