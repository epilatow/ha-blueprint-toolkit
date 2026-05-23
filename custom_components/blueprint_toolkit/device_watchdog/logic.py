# This is AI generated code
"""Business logic for device health watchdog.

Monitors device health across integrations by checking for
unavailable entities and stale state (no state report within
a configurable threshold).
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from .. import helpers


@dataclass
class DeviceEntry:
    """Device discovered during integration scan.

    Locally defined rather than in the shared ``helpers``
    module: only this port consumes the shape today. If a
    second port grows the same need, hoist into helpers.
    """

    id: str

    # Current device name. HA device registry
    # ``device.name_by_user`` (if set) or ``device.name``
    # (set by integration).
    name: str

    # Integration default name. HA device registry
    # ``device.name``. Non-deterministic for
    # multi-integration devices.
    default_name: str

    # Map integrations to the entity ids they provide.
    integration_entities: dict[str, set[str]] = field(
        default_factory=dict,
    )


# Check identifiers surfaced as blueprint options. Adding
# a new check = one new constant, add it to ``CHECK_ALL``,
# and test ``in config.enabled_checks`` at the use site.
CHECK_UNAVAILABLE_ENTITIES = "unavailable-entities"
CHECK_DEVICE_UPDATES = "device-updates"
CHECK_DISABLED_DIAGNOSTICS = "disabled-diagnostics"

CHECK_ALL: frozenset[str] = frozenset(
    {
        CHECK_UNAVAILABLE_ENTITIES,
        CHECK_DEVICE_UPDATES,
        CHECK_DISABLED_DIAGNOSTICS,
    },
)


@dataclass
class Config:
    """Configuration parameters (set per-instance)."""

    exclude_device_name_regex: str
    exclude_entity_id_regex: str
    monitored_entity_domains: list[str]
    dead_threshold_seconds: int
    enabled_checks: frozenset[str]
    # When true, a disabled-diagnostic finding is emitted
    # as a one-click Repair issue instead of a persistent
    # notification. The logic decides which surface at
    # build time (never both) so the user never sees the
    # same finding twice.
    create_repairs: bool = False
    # Per-instance notification ID prefix, ending with
    # the canonical ``__`` separator. Every notification
    # this module mints must start with this string so
    # the service wrapper's orphan sweep can safely scope
    # dismissals to one instance.
    notification_prefix: str = ""
    # Carried onto every ``PersistentNotification`` we
    # construct so the dispatcher can prepend
    # ``Automation: [name](edit-link)\n`` to the body.
    # ``None`` in pure-Python tests where the Config
    # carries no real instance binding.
    instance_id: str | None = None


@dataclass
class EntityInfo:
    """Entity state snapshot for health evaluation."""

    entity_id: str
    state: str
    last_reported: datetime | None


@dataclass
class RegistryEntry:
    """Minimal entity registry entry for diagnostics."""

    entity_id: str
    original_name: str
    platform: str
    entity_category: str | None
    disabled: bool


@dataclass
class DeviceInfo:
    """Device with its entity state snapshots."""

    de: DeviceEntry
    entities: list[EntityInfo] = field(
        default_factory=list,
    )
    registry_entries: list[RegistryEntry] = field(
        default_factory=list,
    )


@dataclass
class DeviceResult:
    """Per-device evaluation result."""

    device_id: str
    device_name: str
    has_issue: bool
    device_excluded: bool
    notification_id: str
    notification_title: str
    notification_message: str
    unavailable_entities: list[str]
    is_stale: bool
    newest_entity: str | None
    newest_timestamp: datetime | None
    entities_evaluated: int
    entities_filtered: int
    # Stamped from ``Config.instance_id`` at evaluation
    # time so ``to_notification`` can hand the dispatcher
    # the automation entity_id needed for the
    # ``Automation: [name](edit-link)\n`` body prefix.
    instance_id: str | None = None
    # Device context the dispatcher renders into the shared
    # attribution header (``Device`` / ``Config Entry``); None
    # for the excluded / no-issue dismiss spec.
    device: helpers.DeviceRef | None = None
    # The device's integration domains, rendered as the
    # attribution ``Integrations`` line (independent of
    # ``device`` so the spec can carry them).
    integrations: tuple[str, ...] = ()

    def to_notification(
        self,
        suppress: bool = False,
    ) -> helpers.PersistentNotification:
        return helpers.PersistentNotification(
            active=self.has_issue and not suppress,
            notification_id=self.notification_id,
            title=self.notification_title,
            message=self.notification_message,
            instance_id=self.instance_id,
            device=self.device,
            integrations=self.integrations,
        )


# Recommended diagnostic entities per integration.
# Matched via original_name on entity_category=diagnostic
# entries. If an entity with the name exists but is
# disabled, the user is notified. If it doesn't exist
# at all, it's silently skipped (device doesn't support
# it).
RECOMMENDED_DIAGNOSTICS: dict[str, list[str]] = {
    "zwave_js": [
        "Last seen",
        "Node status",
        "Signal strength",
        "Battery level",
        "Round trip time",
        "Successful commands (RX)",
        "Successful commands (TX)",
        "Commands dropped (RX)",
        "Commands dropped (TX)",
        "Timed out responses",
    ],
    "bthome": ["Signal strength"],
    "shelly": ["RSSI"],
    "unifiprotect": ["Wi-Fi signal strength", "Uptime"],
}


@dataclass
class DisabledDiagnostic:
    """One disabled recommended diagnostic entity.

    Surfaced in the per-device notification body (which
    renders ``original_name``) when ``create_repairs`` is
    off; when on, the per-device findings are grouped into
    a single repair issue instead.
    """

    original_name: str
    entity_id: str


class FixServices(StrEnum):
    """DW's repair fix service names.

    Members' values are the HA service names registered
    under the ``blueprint_toolkit`` domain. Defined here in
    the logic layer so the logic can build ``FixService``
    payloads directly; the handler imports the enum for
    ``hass.services.async_register``.
    """

    DEVICE_DISABLED_DIAGNOSTICS = "fix_dw_device_disabled_diagnostics"


@dataclass(frozen=True)
class DisabledDiagnosticsRepair:
    """Rich per-repair payload for a DW disabled-diagnostics fix.

    Built by the logic, stored on the handler's instance
    state keyed by notification_id, and read back by the
    fix service to re-enable exactly the captured entity
    set. Stays off the wire (the issue-registry payload is
    just the notification_id).
    """

    device_id: str
    entity_ids: tuple[str, ...]


@dataclass(frozen=True)
class DwDeviceDisabledDiagnosticsIssue(helpers.Issue):
    KEY: ClassVar[str] = "dw_device_disabled_diagnostics"
    count: str
    device_name: str
    entities: str


# The module's issue export; ``test_issues.py`` checks it
# against the ``issues.*`` entries in strings.json / en.json.
ISSUES: tuple[type[helpers.Issue], ...] = (DwDeviceDisabledDiagnosticsIssue,)


def check_disabled_diagnostics(
    integration: str,
    entries: list[RegistryEntry],
) -> list[DisabledDiagnostic]:
    """Check for disabled recommended diagnostic entities.

    Returns one ``DisabledDiagnostic`` per disabled entity;
    entities that don't exist at all are silently skipped.
    """
    recommended = RECOMMENDED_DIAGNOSTICS.get(
        integration,
        [],
    )
    if not recommended:
        return []

    # Filter to diagnostic entities for this integration
    diag_entries = [
        e
        for e in entries
        if e.platform == integration and e.entity_category == "diagnostic"
    ]

    disabled: list[DisabledDiagnostic] = []
    for name in recommended:
        for entry in diag_entries:
            if entry.original_name == name:
                if entry.disabled:
                    disabled.append(
                        DisabledDiagnostic(
                            original_name=name,
                            entity_id=entry.entity_id,
                        ),
                    )
                break
    return disabled


def evaluate_diagnostics(
    config: Config,
    devices: list[DeviceInfo],
) -> tuple[
    list[helpers.PersistentNotification],
    dict[str, DisabledDiagnosticsRepair],
]:
    """Check all devices for disabled diagnostics.

    Returns the per-device spec batch plus the per-repair
    payloads (keyed by notification_id) the handler stashes
    on instance state.

    With ``config.create_repairs`` on, a device's disabled
    diagnostics become a single one-click Repair issue (the
    spec carries ``repair_callback`` + translation data).
    With it off, they render as the per-device persistent-
    notification body. Never both --
    the surface is chosen here at build time, so the same
    finding never appears on two surfaces; the per-backend
    sweep clears the other surface when the toggle flips.

    Devices with no disabled diagnostics emit nothing; the
    dispatcher's prefix sweep removes any prior-run artifact
    for them. Skips devices with no integrations in
    RECOMMENDED_DIAGNOSTICS.
    """
    results: list[helpers.PersistentNotification] = []
    repairs: dict[str, DisabledDiagnosticsRepair] = {}
    for device in devices:
        integrations = sorted(
            device.de.integration_entities.keys(),
        )
        has_recommendations = [
            i for i in integrations if i in RECOMMENDED_DIAGNOSTICS
        ]
        if not has_recommendations:
            continue
        disabled: list[DisabledDiagnostic] = []
        for integration in integrations:
            disabled += check_disabled_diagnostics(
                integration,
                device.registry_entries,
            )
        if not disabled:
            continue
        # Shared affected-entity list -- identical text on both
        # the repair-issue body and the persistent-notification
        # body so the two surfaces stay consistent. entity_id in
        # a code span (constrained charset, markdown-safe);
        # original_name md_escaped (user-controllable).
        entity_lines = "\n".join(
            f"- `{d.entity_id}` ({helpers.md_escape(d.original_name)})"
            for d in disabled
        )
        device_ref = helpers.DeviceRef(
            device_id=device.de.id,
            name=device.de.name or device.de.id,
        )
        device_integrations = tuple(sorted(device.de.integration_entities))
        if config.create_repairs:
            nid = helpers.repair_notification_id(
                config.notification_prefix,
                FixServices.DEVICE_DISABLED_DIAGNOSTICS,
                device.de.id,
            )
            results.append(
                helpers.PersistentNotification(
                    active=True,
                    notification_id=nid,
                    title="",
                    message="",
                    instance_id=config.instance_id,
                    repair_callback=helpers.FixService(
                        service_name=(
                            FixServices.DEVICE_DISABLED_DIAGNOSTICS.value
                        ),
                        notification_id=nid,
                    ),
                    translation_key=(DwDeviceDisabledDiagnosticsIssue.KEY),
                    translation_placeholders=asdict(
                        DwDeviceDisabledDiagnosticsIssue(
                            device_name=device.de.name or device.de.id,
                            count=str(len(disabled)),
                            entities=entity_lines,
                        )
                    ),
                    device=device_ref,
                    integrations=device_integrations,
                ),
            )
            repairs[nid] = DisabledDiagnosticsRepair(
                device_id=device.de.id,
                entity_ids=tuple(d.entity_id for d in disabled),
            )
        else:
            message = (
                f"Recommended diagnostic entities are disabled:"
                f"\n\n{entity_lines}"
            )
            results.append(
                helpers.PersistentNotification(
                    active=True,
                    notification_id=(
                        f"{config.notification_prefix}diag_{device.de.id}"
                    ),
                    title=device.de.name,
                    message=message,
                    instance_id=config.instance_id,
                    device=device_ref,
                    integrations=device_integrations,
                ),
            )
    return results, repairs


def _filter_entities(
    config: Config,
    entities: list[EntityInfo],
) -> tuple[list[EntityInfo], list[EntityInfo]]:
    """Apply domain and regex filters to entities.

    Returns (kept, filtered_out).
    """
    kept: list[EntityInfo] = []
    filtered_out: list[EntityInfo] = []

    domains = [d.lower() for d in config.monitored_entity_domains]
    filter_by_domain = len(domains) > 0

    for entity in entities:
        eid = entity.entity_id
        domain = eid.split(".")[0] if "." in eid else ""

        if filter_by_domain and domain not in domains:
            filtered_out.append(entity)
            continue

        if helpers.matches_pattern(
            eid,
            config.exclude_entity_id_regex,
        ):
            filtered_out.append(entity)
            continue

        kept.append(entity)

    return kept, filtered_out


def _check_staleness(
    entities: list[EntityInfo],
    threshold_seconds: int,
    current_time: datetime,
) -> tuple[bool, str | None, datetime | None]:
    """Check if all entities are stale.

    Returns (is_stale, newest_entity_id, newest_timestamp).
    A device is stale if no entity has been reported within
    the threshold window. Entities without a last_reported
    timestamp are skipped. If no entity has a usable
    timestamp, staleness is indeterminate -- return False.
    """
    if not entities:
        return False, None, None

    newest_entity: str | None = None
    newest_ts: datetime | None = None

    for entity in entities:
        if entity.last_reported is None:
            continue
        if newest_ts is None or entity.last_reported > newest_ts:
            newest_ts = entity.last_reported
            newest_entity = entity.entity_id

    if newest_ts is None:
        return False, None, None

    age_seconds = (current_time - newest_ts).total_seconds()
    is_stale = age_seconds > threshold_seconds

    return is_stale, newest_entity, newest_ts


def _build_notification_message(
    unavailable: list[EntityInfo],
    is_stale: bool,
    newest_entity: str | None,
    newest_timestamp: datetime | None,
    config: Config,
) -> str:
    """Build the notification body for an unhealthy device.

    Carries only the unavailable / stale findings. The
    ``Automation`` / ``Integrations`` / ``Device`` header is
    rendered by the dispatcher from the spec's ``device`` ref.
    """
    lines: list[str] = []

    for entity in sorted(unavailable, key=lambda e: e.entity_id):
        lines.append(
            f"Unavailable entity: {helpers.md_escape(entity.entity_id)}",
        )

    if is_stale:
        threshold_minutes = config.dead_threshold_seconds // 60
        if newest_timestamp and newest_entity:
            last_seen = newest_timestamp.isoformat()
            lines.append(
                f"No entity state report within {threshold_minutes}"
                f" minutes. Most recent update {last_seen}"
                f" via {helpers.md_escape(newest_entity)}.",
            )
        else:
            lines.append(
                f"No entity state report within {threshold_minutes}"
                " minutes. No prior updates detected.",
            )

    # Guard the contract: callers must only invoke this when
    # there's actual unavailable / stale content. Explicit
    # ``ValueError`` (not ``assert``) so the invariant holds
    # under ``python -O`` too.
    if not lines:
        msg = "Expected unavailable or stale content but got none"
        raise ValueError(msg)

    return "\n".join(lines)


def _evaluate_device(
    config: Config,
    device: DeviceInfo,
    current_time: datetime,
) -> DeviceResult:
    """Evaluate health of a single device."""
    notification_id = f"{config.notification_prefix}device_{device.de.id}"

    # Skip excluded devices
    device_excluded = helpers.matches_pattern(
        device.de.name,
        config.exclude_device_name_regex,
    )
    if device_excluded:
        return DeviceResult(
            device_id=device.de.id,
            device_name=device.de.name,
            has_issue=False,
            device_excluded=True,
            notification_id=notification_id,
            notification_title="",
            notification_message="",
            unavailable_entities=[],
            is_stale=False,
            newest_entity=None,
            newest_timestamp=None,
            entities_evaluated=0,
            entities_filtered=0,
            instance_id=config.instance_id,
        )

    kept, filtered_out = _filter_entities(
        config,
        device.entities,
    )

    if CHECK_UNAVAILABLE_ENTITIES in config.enabled_checks:
        unavailable = [e for e in kept if e.state in ("unavailable", "unknown")]
    else:
        unavailable = []

    if CHECK_DEVICE_UPDATES in config.enabled_checks:
        is_stale, newest_entity, newest_ts = _check_staleness(
            kept,
            config.dead_threshold_seconds,
            current_time,
        )
    else:
        is_stale, newest_entity, newest_ts = False, None, None

    has_issue = bool(unavailable) or is_stale

    message = ""
    title = ""
    if has_issue:
        # Title carries just the per-device category; the
        # dispatcher prepends ``<automation_name>: ``.
        title = device.de.name
        message = _build_notification_message(
            unavailable,
            is_stale,
            newest_entity,
            newest_ts,
            config,
        )

    return DeviceResult(
        device_id=device.de.id,
        device_name=device.de.name,
        has_issue=has_issue,
        device_excluded=False,
        notification_id=notification_id,
        notification_title=title,
        notification_message=message,
        unavailable_entities=[e.entity_id for e in unavailable],
        is_stale=is_stale,
        newest_entity=newest_entity,
        newest_timestamp=newest_ts,
        entities_evaluated=len(kept),
        entities_filtered=len(filtered_out),
        instance_id=config.instance_id,
        device=helpers.DeviceRef(
            device_id=device.de.id,
            name=device.de.name or device.de.id,
        ),
        integrations=tuple(sorted(device.de.integration_entities)),
    )


def evaluate_devices(
    config: Config,
    devices: list[DeviceInfo],
    current_time: datetime,
) -> list[DeviceResult]:
    """Evaluate health of all devices.

    Main entry point for the logic module.

    The service wrapper triggers every minute via a time
    pattern.  An interval gate checks whether enough time
    has passed since the last evaluation.

    When the gate passes, the wrapper:
    1. Discovers devices across configured integrations
       using the HA entity and device registries
    2. Reads entity state for each device
    3. Calls this function with the device list

    For each device, this function:
    1. Filters entities by domain and exclude regex
    2. Checks for unavailable/unknown entity states
       (gated by CHECK_UNAVAILABLE_ENTITIES in
       config.enabled_checks)
    3. Checks for staleness (no state report within
       threshold; gated by CHECK_DEVICE_UPDATES in
       config.enabled_checks)
    4. Returns a DeviceResult per device

    The wrapper then creates persistent notifications
    for unhealthy devices and dismisses them on recovery.
    """
    results: list[DeviceResult] = []
    for device in devices:
        result = _evaluate_device(
            config,
            device,
            current_time,
        )
        results.append(result)
    return results


@dataclass
class DirectiveInputs:
    """Per-instance include / exclude directive inputs for DW.

    Carries the user-supplied directive lists + the enabled
    toggle + the candidate sets the regex / entity-id
    validators measure against.

    The handler builds ``device_name_candidates`` and
    ``entity_id_candidates`` from the FULL device + entity
    registries (NOT filtered by include / exclude
    integrations), with ``entity_id_candidates`` narrowed to
    ``monitored_entity_domains`` only. Reason: the
    integration filter and the regex filter are independent
    layers from the user's perspective, but the actual
    exclusion code applies them in a fixed order
    (integration first, regex after). If the validator
    measured against the post-integration-filter set, a
    user with both layers configured would see "unmatched
    regex" warnings whenever the integration filter already
    pruned the entities the regex would have matched -- a
    confusing leak of internal ordering.
    """

    enabled: bool
    include_integrations: list[str]
    exclude_integrations: list[str]
    exclude_device_name_regex_lines: list[helpers.JoinedRegexLine]
    exclude_entity_id_regex_lines: list[helpers.JoinedRegexLine]
    device_name_candidates: frozenset[str]
    entity_id_candidates: frozenset[str]


@dataclass
class EvaluationResult:
    """Full evaluation result for the service wrapper."""

    results: list[DeviceResult]
    notifications: list[helpers.PersistentNotification]
    all_integrations_count: int
    stat_entities: int
    stat_devices_excluded: int
    stat_entities_excluded: int
    issues_count: int
    stat_entity_issues: int
    stat_stale: int
    # Per-repair payloads (keyed by notification_id) the
    # handler stashes on instance state so the fix service
    # can recover the exact entity set without re-walking.
    # Empty when ``create_repairs`` is off (findings render
    # as notifications instead).
    repairs: dict[str, DisabledDiagnosticsRepair] = field(
        default_factory=dict,
    )
    unmatched_directives: list[helpers.UnmatchedDirective] = field(
        default_factory=list,
    )


def _validate_dw_directives(
    inputs: DirectiveInputs,
    all_integrations: list[str],
) -> list[helpers.UnmatchedDirective]:
    """Compose the per-category validators into DW's unmatched list.

    Integration directives match against
    ``all_integrations`` (the full set the handler
    enumerated). Device-name and entity-id regexes match
    against the candidate sets the handler pre-built from
    the full registries (see ``DirectiveInputs`` for the
    rationale -- candidates are deliberately broader than
    the post-include/exclude-integration set so the
    validator doesn't leak the actual exclusion code's
    layer ordering).
    """
    if not inputs.enabled:
        return []

    integration_candidates = frozenset(all_integrations)

    out: list[helpers.UnmatchedDirective] = []
    out.extend(
        helpers.validate_directives_item(
            field="include_integrations",
            directives=inputs.include_integrations,
            candidates=integration_candidates,
            reason="unknown integration",
        ),
    )
    out.extend(
        helpers.validate_directives_item(
            field="exclude_integrations",
            directives=inputs.exclude_integrations,
            candidates=integration_candidates,
            reason="unknown integration",
        ),
    )
    out.extend(
        helpers.validate_directives_regex(
            field="exclude_device_name_regex",
            lines=inputs.exclude_device_name_regex_lines,
            candidates=inputs.device_name_candidates,
        ),
    )
    out.extend(
        helpers.validate_directives_regex(
            field="exclude_entity_id_regex",
            lines=inputs.exclude_entity_id_regex_lines,
            candidates=inputs.entity_id_candidates,
        ),
    )
    return out


_DISABLED_DIRECTIVES = DirectiveInputs(
    enabled=False,
    include_integrations=[],
    exclude_integrations=[],
    exclude_device_name_regex_lines=[],
    exclude_entity_id_regex_lines=[],
    device_name_candidates=frozenset(),
    entity_id_candidates=frozenset(),
)


def run_evaluation(
    config: Config,
    devices: list[DeviceInfo],
    current_time: datetime,
    all_integrations: list[str],
    max_notifications: int,
    directive_inputs: DirectiveInputs | None = None,
) -> EvaluationResult:
    """Run device evaluation in a worker thread.

    Called from the handler via
    ``hass.async_add_executor_job`` so the heavy per-device
    classification + notification body assembly stays off
    the event loop. The handler builds the device list on
    the loop (registries are loop-only) then hands it off
    here.
    """
    results = evaluate_devices(config, devices, current_time)

    diag_notifications: list[helpers.PersistentNotification] = []
    diag_repairs: dict[str, DisabledDiagnosticsRepair] = {}
    if CHECK_DISABLED_DIAGNOSTICS in config.enabled_checks:
        diag_notifications, diag_repairs = evaluate_diagnostics(
            config,
            devices,
        )

    notifications = helpers.prepare_notifications(
        results,
        max_notifications=max_notifications,
        cap_notification_id=f"{config.notification_prefix}cap",
        cap_title="Notification cap reached",
        cap_item_label="devices with issues",
        instance_id=config.instance_id,
    )
    notifications += diag_notifications

    issues = [r for r in results if r.has_issue]
    unmatched = _validate_dw_directives(
        directive_inputs
        if directive_inputs is not None
        else _DISABLED_DIRECTIVES,
        all_integrations,
    )

    return EvaluationResult(
        results=results,
        notifications=notifications,
        all_integrations_count=len(all_integrations),
        stat_entities=sum(
            r.entities_evaluated + r.entities_filtered
            for r in results
            if not r.device_excluded
        ),
        stat_devices_excluded=sum(1 for r in results if r.device_excluded),
        stat_entities_excluded=sum(r.entities_filtered for r in results),
        issues_count=len(issues),
        stat_entity_issues=sum(len(r.unavailable_entities) for r in issues),
        stat_stale=sum(1 for r in issues if r.is_stale),
        repairs=diag_repairs,
        unmatched_directives=unmatched,
    )
