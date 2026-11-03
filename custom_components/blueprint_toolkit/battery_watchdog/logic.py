# This is AI generated code
"""Business logic for the battery watchdog.

A battery is low when it is a numeric battery sensor whose
level is from 0 up to and including the warning level, or a
binary battery sensor that is ``on``. Any other state --
``unavailable``, ``unknown``, a non-numeric level -- is not
a low battery; reporting unavailable entities is Device
Watchdog's job.

Every low battery the include / exclude inputs leave in
scope lands in one per-instance notification, one line per
battery, sorted by area (batteries with no area last) and
then device::

    - <area> -> <device>: <level>

A battery with no area drops the ``<area> -> `` prefix. The
device links to its device page and the level links to the
battery entity's history. A battery with no device shows its
own name, unlinked; a device with more than one low battery
names each battery after the device.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import helpers

# Shown in place of a level for a binary battery sensor.
BINARY_LOW = "low"


@dataclass(frozen=True)
class BatteryDevice:
    """The device a battery belongs to.

    ``integrations`` is every integration with an entity on
    the device, so an excluded integration excludes the
    whole device.
    """

    device_id: str
    name: str
    integrations: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BatteryInfo:
    """One battery-class entity with a state.

    ``binary`` marks a ``binary_sensor`` (``on`` means low)
    as opposed to a numeric ``sensor`` reporting a level.
    ``area`` is the name of the area HA places the entity
    in.
    """

    entity_id: str
    name: str
    integration: str
    state: str
    binary: bool
    device: BatteryDevice | None = None
    area: str | None = None


@dataclass
class Config:
    """Configuration parameters (set per-instance).

    A non-empty ``include_entities`` limits the watchdog to
    exactly those entities, and the other include / exclude
    fields are then not consulted. Otherwise an exclude
    wins over an include, as in the other watchdogs.
    """

    warning_level: int
    include_integrations: frozenset[str] = frozenset()
    exclude_integrations: frozenset[str] = frozenset()
    include_entities: frozenset[str] = frozenset()
    exclude_entities: frozenset[str] = frozenset()
    exclude_device_name_regex: str = ""
    exclude_entity_id_regex: str = ""
    exclude_entity_name_regex: str = ""
    # Per-instance notification ID prefix, ending with the
    # canonical ``__`` separator.
    notification_prefix: str = ""
    # Automation entity_id for the dispatcher's attribution
    # header; ``None`` in pure-Python tests.
    instance_id: str | None = None


@dataclass
class DirectiveInputs:
    """Include / exclude directives to check for matching nothing.

    Every directive is measured against the battery entities
    alone, before any filter applies: an integration,
    entity, or regex line that touches no battery would
    filter nothing, while one another filter merely shadows
    still names a battery.
    """

    enabled: bool
    include_integrations: list[str]
    exclude_integrations: list[str]
    include_entities: list[str]
    exclude_entities: list[str]
    exclude_device_name_regex_lines: list[helpers.JoinedRegexLine]
    exclude_entity_id_regex_lines: list[helpers.JoinedRegexLine]
    exclude_entity_name_regex_lines: list[helpers.JoinedRegexLine]


@dataclass
class EvaluationResult:
    """What one scan found, for the handler to dispatch."""

    notification: helpers.PersistentNotification
    batteries: int
    batteries_excluded: int
    low: list[BatteryInfo]
    unmatched_directives: list[helpers.UnmatchedDirective] = field(
        default_factory=list,
    )


def battery_level(battery: BatteryInfo) -> float | None:
    """A numeric battery's level, or ``None`` if it has none."""
    if battery.binary:
        return None
    try:
        return float(battery.state)
    except ValueError:
        return None


def is_low(battery: BatteryInfo, warning_level: int) -> bool:
    """Whether ``battery`` reports a low battery."""
    if battery.binary:
        return battery.state == "on"
    level = battery_level(battery)
    return level is not None and 0 <= level <= warning_level


def is_excluded(config: Config, battery: BatteryInfo) -> bool:
    """Whether the include / exclude inputs drop ``battery``."""
    if config.include_entities:
        return battery.entity_id not in config.include_entities
    if (
        config.include_integrations
        and battery.integration not in config.include_integrations
    ):
        return True
    if battery.integration in config.exclude_integrations:
        return True
    if battery.entity_id in config.exclude_entities:
        return True
    if helpers.matches_pattern(
        battery.entity_id, config.exclude_entity_id_regex
    ):
        return True
    if helpers.matches_pattern(battery.name, config.exclude_entity_name_regex):
        return True
    device = battery.device
    return device is not None and (
        bool(device.integrations & config.exclude_integrations)
        or helpers.matches_pattern(
            device.name, config.exclude_device_name_regex
        )
    )


def _level_text(battery: BatteryInfo) -> str:
    level = battery_level(battery)
    if level is None:
        return BINARY_LOW
    return f"{level:g}%"


def _sort_key(battery: BatteryInfo) -> tuple[bool, str, str, str]:
    return (
        battery.area is None,
        (battery.area or "").casefold(),
        (battery.device.name if battery.device else battery.name).casefold(),
        battery.name.casefold(),
    )


def render_lines(low: list[BatteryInfo]) -> list[str]:
    """One markdown bullet per low battery, sorted by area and device."""
    per_device: dict[str, int] = {}
    for battery in low:
        if battery.device is not None:
            device_id = battery.device.device_id
            per_device[device_id] = per_device.get(device_id, 0) + 1
    lines: list[str] = []
    for battery in sorted(low, key=_sort_key):
        area = f"{helpers.md_escape(battery.area)} -> " if battery.area else ""
        if battery.device is None:
            device = helpers.md_escape(battery.name)
        else:
            device = helpers.device_link(
                battery.device.name, battery.device.device_id
            )
            if per_device[battery.device.device_id] > 1:
                device = f"{device} ({helpers.md_escape(battery.name)})"
        level = helpers.entity_history_link(
            _level_text(battery), battery.entity_id
        )
        lines.append(f"- {area}{device}: {level}")
    return lines


def _validate_bw_directives(
    inputs: DirectiveInputs,
    batteries: list[BatteryInfo],
) -> list[helpers.UnmatchedDirective]:
    """Every include / exclude directive that touches no battery."""
    if not inputs.enabled:
        return []
    # An include keeps a battery by its own integration; an
    # exclude also drops every battery on a device the
    # integration has an entity on.
    battery_integrations = frozenset(
        b.integration for b in batteries if b.integration
    )
    device_integrations = battery_integrations | frozenset(
        i for b in batteries if b.device for i in b.device.integrations
    )
    entity_ids = frozenset(b.entity_id for b in batteries)
    out: list[helpers.UnmatchedDirective] = []
    out.extend(
        helpers.validate_directives_item(
            field="include_integrations",
            directives=inputs.include_integrations,
            candidates=battery_integrations,
            reason="no battery from this integration",
        ),
    )
    out.extend(
        helpers.validate_directives_item(
            field="exclude_integrations",
            directives=inputs.exclude_integrations,
            candidates=device_integrations,
            reason="no battery on this integration's devices",
        ),
    )
    for name, directives in (
        ("include_entities", inputs.include_entities),
        ("exclude_entities", inputs.exclude_entities),
    ):
        out.extend(
            helpers.validate_directives_item(
                field=name,
                directives=directives,
                candidates=entity_ids,
                reason="not a battery entity",
            ),
        )
    out.extend(
        helpers.validate_directives_regex(
            field="exclude_device_name_regex",
            lines=inputs.exclude_device_name_regex_lines,
            candidates=frozenset(b.device.name for b in batteries if b.device),
        ),
    )
    out.extend(
        helpers.validate_directives_regex(
            field="exclude_entity_id_regex",
            lines=inputs.exclude_entity_id_regex_lines,
            candidates=entity_ids,
        ),
    )
    out.extend(
        helpers.validate_directives_regex(
            field="exclude_entity_name_regex",
            lines=inputs.exclude_entity_name_regex_lines,
            candidates=frozenset(b.name for b in batteries),
        ),
    )
    return out


def run_evaluation(
    config: Config,
    batteries: list[BatteryInfo],
    directive_inputs: DirectiveInputs,
) -> EvaluationResult:
    """Find the low batteries in scope and build their notification.

    The notification is inactive when nothing is low, so a
    scan that finds no low battery dismisses the prior one.
    """
    in_scope = [b for b in batteries if not is_excluded(config, b)]
    low = [b for b in in_scope if is_low(b, config.warning_level)]
    noun = "battery" if len(low) == 1 else "batteries"
    notification = helpers.PersistentNotification(
        active=bool(low),
        notification_id=f"{config.notification_prefix}low_batteries",
        title=f"{len(low)} low {noun}" if low else "",
        message="\n".join(render_lines(low)),
        instance_id=config.instance_id,
    )
    return EvaluationResult(
        notification=notification,
        batteries=len(batteries),
        batteries_excluded=len(batteries) - len(in_scope),
        low=low,
        unmatched_directives=_validate_bw_directives(
            directive_inputs, batteries
        ),
    )
