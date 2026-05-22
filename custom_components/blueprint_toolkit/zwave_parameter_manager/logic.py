# This is AI generated code
"""Logic for declarative, device-agnostic Z-Wave parameter mgmt.

Pure functions over dataclasses. No HA registries, no socket.io.

Three things live here:

- The **GenericParam catalog** -- the abstract, device-agnostic
  settings (``motion_sensitivity``, ``light_on_motion``, ...). These
  are defined in code; they are the abstractions we add as needed.
  Each is named by a ``GenericParamNames`` member so a policy can only
  reference a concept that exists.
- The **mapping table** model -- how each GenericParam locates and is
  expressed on a specific device (a parameter-label match or a fixed
  value id, plus per-model quirks and the option-label classification
  used to read device states). This is DATA: generated from the
  zwave-js config DB and checked in, then loaded and handed to the
  resolver, so it is regenerated without code changes and the logic
  stays pure.
- ``validate_value`` + ``resolve`` + the policy planner.

Strict input, flexible output: user values are validated strictly at
the boundary (``validate_value``); ``resolve`` then consumes a
``ParamValue`` it assumes valid and adapts to whatever the device's
live metadata reports.

The handler builds ``Device``/``ParamMeta`` from HA + zwave-js state;
the CLI builds them from zwave-js-ui. ``node_id`` is the key common to
both and to the network.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum, StrEnum, auto

from .catalog import (
    CATALOG,
    GENERIC_PARAMS,
    GenericParam,
    GenericParamNames,
    ParamRange,
    ParamType,
)

# Re-exported from .catalog for back-compat -- consumers can keep
# importing from ``logic`` while the canonical home for the concept
# definitions moves out to its own focused module.
__all__ = (
    "CATALOG",
    "GENERIC_PARAMS",
    "GenericParam",
    "GenericParamNames",
    "ParamRange",
    "ParamType",
)


# -- Z-Wave protocol ---------------------------------------------


class CommandClass(IntEnum):
    """Z-Wave command classes ZPM reads and writes."""

    CONFIGURATION = 112
    WAKE_UP = 132


# -- ParamValue (the boundary type the resolver consumes) --------


@dataclass(frozen=True)
class ParamValue:
    """A user value for a GenericParam, tagged with its type.

    The single place the ``bool | int | float`` union lives. Build via
    ``of`` so ``param_type`` is taken from the catalog param and can't
    drift from the concept it belongs to.
    """

    param_type: ParamType
    value: bool | int | float

    @classmethod
    def of(
        cls, generic_param: GenericParam, value: bool | int | float
    ) -> ParamValue:
        return cls(generic_param.param_type, value)


# -- Mapping table (data; generated from the DB, checked in) ------


@dataclass(frozen=True)
class LabelMatch:
    """Locate a device param by exact, case-insensitive label."""

    labels: tuple[str, ...]


@dataclass(frozen=True)
class FixedValueId:
    """Locate a device param by a fixed command class + property.

    Used for standardized command classes whose value id is uniform
    across every device (e.g. Wake Up, CC 132).
    """

    command_class: int
    property: int | str


Locator = LabelMatch | FixedValueId


# The one Wake Up value-id ZPM reads and writes. Single source for the
# (command class, property) pair so the settable-param surface, the
# mapping locator for the wake_up_interval concept, and the write path
# all reference it rather than respelling 132 / "wakeUpInterval".
WAKE_UP_INTERVAL_VALUE = FixedValueId(CommandClass.WAKE_UP, "wakeUpInterval")


@dataclass(frozen=True)
class ModelId:
    """Fully-qualified device identity: manufacturer + model.

    A quirk targets a specific device, so a model token alone is
    ambiguous (the same token can recur across manufacturers).
    Requiring both fields structurally enforces "model implies
    manufacturer" at every construction site.
    """

    manufacturer: str
    model: str


@dataclass(frozen=True)
class ModelQuirk:
    """Per-(concept, ModelId) override for what metadata can't express.

    ``invert`` flips a RANGE scale that runs backwards. ``off_value`` /
    ``on_value`` pin a BOOL's raw values for devices whose option
    states don't cleanly name an off/on (e.g. a multi-state LED).
    """

    invert: bool = False
    off_value: int | None = None
    on_value: int | None = None


@dataclass(frozen=True)
class MappingTable:
    """Generic -> device-specific mapping, plus state-label vocab.

    Generated from the zwave-js config DB and checked in (not
    hand-curated); loaded and passed to the resolver. ``locators`` is
    keyed by GenericParam name; ``quirks`` by ``(name, ModelId)``. The
    label sets / tokens classify a device's own option-state labels
    when reading actual state and inferring scale direction.
    """

    locators: Mapping[GenericParamNames, Locator]
    quirks: Mapping[tuple[GenericParamNames, ModelId], ModelQuirk] = field(
        default_factory=dict
    )
    off_labels: frozenset[str] = frozenset()
    on_labels: frozenset[str] = frozenset()
    low_tokens: tuple[str, ...] = ()
    high_tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # The four categories carry domain-distinct vocab (option-state
        # labels vs scale-direction tokens); a string in more than one
        # would let the resolver pick a different category by accident.
        # Match is case-insensitive elsewhere, so the disjoint check
        # casefolds too -- otherwise "Off" and "off" would slip through.
        seen: dict[str, str] = {}
        for category in (
            "off_labels",
            "on_labels",
            "low_tokens",
            "high_tokens",
        ):
            for item in getattr(self, category):
                key = item.casefold()
                if key in seen:
                    raise ValueError(
                        f"mapping: {item!r} appears in both "
                        f"{seen[key]} and {category}"
                    )
                seen[key] = category


# -- Device + parameter metadata (resolver inputs) ---------------


@dataclass(frozen=True)
class ParamMeta:
    """One device parameter as zwave-js reports it.

    ``states`` maps a raw value to its option label (e.g.
    ``{0: "Disable", 1: "Enable"}``); empty for a bare numeric range.
    ``range`` is the inclusive raw ``(min, max)`` bounds, ``None`` when
    the parameter reports none. ``property_key`` is set for bitmask /
    partial parameters.
    """

    command_class: int
    property: int | str
    label: str
    property_key: int | None = None
    range: ParamRange | None = None
    unit: str | None = None
    states: Mapping[int, str] = field(default_factory=dict)


class DeviceType(StrEnum):
    """A device's capability / type tag, used by selectors.

    Sensor-ish tags come from a device's HA entity ``device_class``
    attributes; ``contact`` collapses HA's ``window`` / ``door`` /
    ``garage_door`` (open-close sensors share their config). ``lock``
    and ``siren`` come instead from the presence of those HA entity
    domains. The adapter performs that mapping; this is the closed set
    selectors accept.
    """

    MOTION = auto()
    CONTACT = auto()
    MOISTURE = auto()
    HUMIDITY = auto()
    TEMPERATURE = auto()
    ILLUMINANCE = auto()
    SMOKE = auto()
    CARBON_MONOXIDE = auto()
    LOCK = auto()
    SIREN = auto()


@dataclass(frozen=True)
class Device:
    """A Z-Wave device.

    ``node_id`` is the key common to HA, zwave-js, and the network --
    always present. ``device_id`` is the HA registry UUID, present only
    on the HA-built path (the CLI builds from zwave-js-ui and has no
    HA UUID). ``device_types`` are the device's derived capability tags
    (the adapter maps each node's HA entity ``device_class`` attributes
    and key entity domains -- ``lock``/``siren`` -- onto these).
    ``is_listening`` is the zwave-js node flag: a battery (sleeping)
    device is ``is_listening == False``.
    """

    node_id: int
    name: str
    manufacturer: str
    model: str
    is_listening: bool
    device_id: str | None = None
    device_types: frozenset[DeviceType] = frozenset()
    params: tuple[ParamMeta, ...] = ()


# -- Strict input validation (boundary; argparse consumes this) --


def validate_value(
    generic_param: GenericParam,
    value: object,
) -> list[str]:
    """Validate a raw user-supplied value for a GenericParam.

    Returns a list of config-error strings (empty when valid). This is
    the strict-input gate run at the argparse boundary; on success the
    caller wraps the value in a ``ParamValue`` for ``resolve``. ``bool``
    is excluded from the numeric kinds because it is an ``int``
    subclass.
    """

    name = generic_param.name
    if generic_param.param_type is ParamType.BOOL:
        if not isinstance(value, bool):
            return [f"{name} must be true or false, got {value!r}"]
        return []
    if generic_param.param_type is ParamType.RANGE:
        scale = generic_param.range
        if scale is None:
            return [f"{name} has no scale range"]
        lo, hi = scale
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{name} must be an integer {lo}-{hi}, got {value!r}"]
        if not lo <= value <= hi:
            return [f"{name} must be {lo}-{hi}, got {value}"]
        return []
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return [f"{name} must be a number, got {value!r}"]
    if not math.isfinite(value):
        return [f"{name} must be a finite number, got {value}"]
    if value < 0:
        return [f"{name} must be >= 0, got {value}"]
    return []


# -- Resolution result -------------------------------------------


class ResolutionStatus(Enum):
    """Device-side outcome of resolving a value for one device.

    Input-validity is NOT represented here -- that is ``validate_value``
    at the boundary. These are all about the device + mapping.
    """

    RESOLVED = "resolved"
    NOT_APPLICABLE = "not_applicable"  # warn: device lacks the param
    AMBIGUOUS = "ambiguous"  # error: >1 matching param
    UNMAPPABLE = "unmappable"  # error: param can't express it


@dataclass(frozen=True)
class Resolution:
    """Result of ``resolve``.

    On ``RESOLVED``, the command_class / property / property_key /
    value are the concrete write; otherwise ``reason`` explains the
    warning / error.
    """

    status: ResolutionStatus
    command_class: int | None = None
    property: int | str | None = None
    property_key: int | None = None
    value: int | None = None
    reason: str = ""


# -- Generic param -> device parameter matching ------------------


def matching_params(
    device: Device,
    locator: Locator,
) -> list[ParamMeta]:
    """Return the device parameters a locator selects."""

    if isinstance(locator, FixedValueId):
        return [
            p
            for p in device.params
            if p.command_class == locator.command_class
            and p.property == locator.property
        ]
    wanted = {label.casefold() for label in locator.labels}
    return [p for p in device.params if p.label.casefold() in wanted]


# -- Param-type mapping ------------------------------------------


def labels_to_state_values(
    states: Mapping[int, str],
    labels: frozenset[str],
) -> set[int]:
    """Raw values whose option label is in ``labels`` (case-folded)."""

    return {raw for raw, label in states.items() if label.casefold() in labels}


def labels_to_state_values_one(
    states: Mapping[int, str],
    labels: frozenset[str],
) -> int | None:
    """An arbitrary raw value matching ``labels``, or ``None``.

    For single-state lookups (on/off) where at most one label is
    expected to match.
    """

    return next(iter(labels_to_state_values(states, labels)), None)


def _resolve_bool(
    param: ParamMeta,
    value: bool,
    quirk: ModelQuirk | None,
    mapping: MappingTable,
) -> Resolution:
    """Map true/false onto the device's on/off raw value."""

    if value:
        raw = quirk.on_value if quirk else None
        if raw is None:
            raw = labels_to_state_values_one(param.states, mapping.on_labels)
        if raw is None:
            raw = param.range[1] if param.range else None
    else:
        raw = quirk.off_value if quirk else None
        if raw is None:
            raw = labels_to_state_values_one(param.states, mapping.off_labels)
        if raw is None:
            raw = param.range[0] if param.range else None
    if raw is None:
        side = "on" if value else "off"
        return Resolution(
            ResolutionStatus.UNMAPPABLE,
            reason=f"{param.label!r} has no {side} value",
        )
    return _resolved(param, raw)


def _detect_descending(
    states: Mapping[int, str],
    low_tokens: tuple[str, ...],
    high_tokens: tuple[str, ...],
) -> bool:
    """Fallback direction inference from named option labels.

    Used only when the mapping table has no invert quirk for this
    device. True when a "high"-flavoured label sits at a lower raw
    value than a "low"-flavoured one.
    """

    low_at: int | None = None
    high_at: int | None = None
    for raw, label in states.items():
        folded = label.casefold()
        if low_at is None and any(t in folded for t in low_tokens):
            low_at = raw
        if high_at is None and any(t in folded for t in high_tokens):
            high_at = raw
    if low_at is None or high_at is None:
        return False
    return high_at < low_at


def _resolve_range(
    param: ParamMeta,
    generic_param: GenericParam,
    value: int,
    quirk: ModelQuirk | None,
    mapping: MappingTable,
) -> Resolution:
    """Rescale ``value`` from the concept's scale onto the param range.

    The abstract scale comes from ``generic_param.range``. Direction
    comes from the mapping's per-model invert quirk first; the
    named-option heuristic is only a fallback for devices the table
    doesn't cover.
    """

    scale = generic_param.range
    if scale is None:
        return Resolution(
            ResolutionStatus.UNMAPPABLE,
            reason=f"{generic_param.name} has no scale range",
        )
    if param.range is None:
        return Resolution(
            ResolutionStatus.UNMAPPABLE,
            reason=f"{param.label!r} has no numeric range",
        )
    scale_min, scale_max = scale
    param_min, param_max = param.range
    off_values = labels_to_state_values(param.states, mapping.off_labels)
    # Off-states (e.g. "Disable" at raw 0) sit inside the device's raw
    # range but are not valid targets for a scaled value, so walk both
    # ends inward past any off-state. The rescale then maps onto the
    # contiguous usable block; an off-state stranded mid-block (caught
    # below) has no clean answer and is rejected.
    usable_min = param_min
    while usable_min in off_values and usable_min <= param_max:
        usable_min += 1
    usable_max = param_max
    while usable_max in off_values and usable_max >= usable_min:
        usable_max -= 1
    if usable_max <= usable_min:
        return Resolution(
            ResolutionStatus.UNMAPPABLE,
            reason=f"{param.label!r} has no usable range",
        )
    if any(usable_min < off < usable_max for off in off_values):
        return Resolution(
            ResolutionStatus.UNMAPPABLE,
            reason=f"{param.label!r} has an off value mid-scale",
        )
    span = usable_max - usable_min
    frac = (value - scale_min) / (scale_max - scale_min)
    if quirk is not None:
        descending = quirk.invert
    else:
        descending = _detect_descending(
            param.states, mapping.low_tokens, mapping.high_tokens
        )
    if descending:
        raw = usable_max - round(frac * span)
    else:
        raw = usable_min + round(frac * span)
    return _resolved(param, raw)


_PERCENT_UNITS: dict[str, float] = {
    "%": 1.0,
    "rh%": 1.0,
    "%rh": 1.0,
    "%rf": 1.0,
    "0.1 %": 10.0,
    "0.1 %rh": 10.0,
}
_TIME_UNITS_TO_SECONDS: dict[str, float] = {
    "seconds": 1.0,
    "second": 1.0,
    "minutes": 60.0,
    "minute": 60.0,
    "hours": 3600.0,
    "hour": 3600.0,
}


def _convert_quantity(
    value: float,
    user_unit: str,
    device_unit: str | None,
) -> tuple[int | None, str]:
    """Convert ``value`` (in ``user_unit``) to the param's raw int."""

    du = (device_unit or "").casefold()
    uu = user_unit.casefold()
    if uu in _PERCENT_UNITS or du in _PERCENT_UNITS:
        if du not in _PERCENT_UNITS:
            return None, f"unhandled percent device unit {device_unit!r}"
        return round(value * _PERCENT_UNITS[du]), ""
    if uu in _TIME_UNITS_TO_SECONDS:
        per_raw = _TIME_UNITS_TO_SECONDS.get(du)
        if per_raw is None:
            return None, f"unhandled time device unit {device_unit!r}"
        return round(value * _TIME_UNITS_TO_SECONDS[uu] / per_raw), ""
    return None, f"unhandled unit conversion {user_unit!r}->{device_unit!r}"


def _resolve_value(
    param: ParamMeta,
    generic_param: GenericParam,
    value: float,
) -> Resolution:
    if generic_param.units is None:
        return Resolution(
            ResolutionStatus.UNMAPPABLE,
            reason=f"{generic_param.name} has no unit",
        )
    raw, reason = _convert_quantity(value, generic_param.units, param.unit)
    if raw is None:
        return Resolution(ResolutionStatus.UNMAPPABLE, reason=reason)
    if param.range is not None:
        param_min, param_max = param.range
        raw = max(param_min, min(raw, param_max))
    return _resolved(param, raw)


def _resolved(param: ParamMeta, value: int) -> Resolution:
    return Resolution(
        ResolutionStatus.RESOLVED,
        command_class=param.command_class,
        property=param.property,
        property_key=param.property_key,
        value=value,
    )


def resolve(
    device: Device,
    generic_param: GenericParam,
    mapping: MappingTable,
    value: ParamValue,
) -> Resolution:
    """Resolve a validated value onto ``device`` via the mapping.

    Precondition: ``value`` carries a scalar that already passed
    ``validate_value`` for ``generic_param`` (so the type matches the
    param type and is in range). Returns a device-side ``Resolution`` --
    RESOLVED with the concrete write, NOT_APPLICABLE (no matching param
    -> warning), AMBIGUOUS (>1 match -> error), or UNMAPPABLE (param
    can't express it).
    """

    locator = mapping.locators.get(generic_param.name)
    if locator is None:
        return Resolution(
            ResolutionStatus.UNMAPPABLE,
            reason=f"no mapping for {generic_param.name}",
        )
    matches = matching_params(device, locator)
    if not matches:
        return Resolution(
            ResolutionStatus.NOT_APPLICABLE,
            reason=(f"{generic_param.name} not supported by {device.model}"),
        )
    if len(matches) > 1:
        labels = ", ".join(sorted(p.label for p in matches))
        return Resolution(
            ResolutionStatus.AMBIGUOUS,
            reason=f"{generic_param.name} matches: {labels}",
        )
    param = matches[0]
    quirk = mapping.quirks.get(
        (generic_param.name, ModelId(device.manufacturer, device.model))
    )
    raw_value = value.value
    if generic_param.param_type is ParamType.BOOL:
        assert isinstance(raw_value, bool)
        return _resolve_bool(param, raw_value, quirk, mapping)
    if generic_param.param_type is ParamType.RANGE:
        assert isinstance(raw_value, int) and not isinstance(raw_value, bool)
        return _resolve_range(param, generic_param, raw_value, quirk, mapping)
    assert not isinstance(raw_value, bool)
    return _resolve_value(param, generic_param, float(raw_value))


# -- Selectors + policies ----------------------------------------


class Power(StrEnum):
    """A device's power source, derived from the listening flag."""

    BATTERY = auto()  # sleeping node (is_listening == False)
    MAINS = auto()  # always-listening node (is_listening == True)


@dataclass(frozen=True)
class Selector:
    """Device-matching criteria for a policy (AND of present fields).

    ``power`` selects on the device's power source. ``manufacturer`` /
    ``model`` match case-insensitively. ``device_type`` matches one of
    a device's derived ``device_types``.
    """

    manufacturer: str | None = None
    model: str | None = None
    power: Power | None = None
    device_type: DeviceType | None = None


@dataclass(frozen=True)
class Policy:
    """A selector plus the GenericParam values to apply to matches."""

    name: str
    match: Selector
    settings: Mapping[GenericParamNames, ParamValue]
    exclude: tuple[Selector, ...] = ()


def _ci_eq(a: str | None, b: str) -> bool:
    return a is not None and a.casefold() == b.casefold()


def selector_matches(selector: Selector, device: Device) -> bool:
    """True when ``device`` satisfies every present criterion."""

    if selector.manufacturer is not None and not _ci_eq(
        selector.manufacturer, device.manufacturer
    ):
        return False
    if selector.model is not None and not _ci_eq(selector.model, device.model):
        return False
    if selector.power is not None:
        is_battery = not device.is_listening
        if is_battery != (selector.power is Power.BATTERY):
            return False
    if (
        selector.device_type is not None
        and selector.device_type not in device.device_types
    ):
        return False
    return True


def policy_matches(policy: Policy, device: Device) -> bool:
    """True when the policy includes ``device`` and excludes none."""

    if not selector_matches(policy.match, device):
        return False
    return not any(selector_matches(ex, device) for ex in policy.exclude)


@dataclass(frozen=True)
class PlannedWrite:
    """One concrete parameter write planned for a device.

    Carries the resolved ``Device`` (not just its node id) so reports
    and the apply path can name + address the device directly.
    """

    device: Device
    concept: GenericParamNames
    policy: str
    command_class: int
    property: int | str
    property_key: int | None
    value: int


@dataclass(frozen=True)
class PlanIssue:
    """A warning or error surfaced while planning.

    Carries the ``Device`` (not just its node id) so the surfaced
    warning / error can name the device for the operator.
    """

    device: Device
    concept: GenericParamNames
    reason: str


@dataclass(frozen=True)
class Plan:
    """Result of ``evaluate_policies``.

    ``writes`` are the concrete writes; ``warnings`` are
    not-applicable concepts (a selected device lacks the parameter);
    ``errors`` are conflicts and unmappable values.
    """

    writes: tuple[PlannedWrite, ...] = ()
    warnings: tuple[PlanIssue, ...] = ()
    errors: tuple[PlanIssue, ...] = ()


def evaluate_policies(
    devices: Sequence[Device],
    policies: Sequence[Policy],
    mapping: MappingTable,
) -> Plan:
    """Plan every policy against every device using ``mapping``.

    Two policies setting the same concept on one device is a hard
    error (no implicit ordering). A selected device lacking a
    parameter for a concept is a warning, not an error. Values are
    assumed already validated by ``validate_value``.
    """

    writes: list[PlannedWrite] = []
    warnings: list[PlanIssue] = []
    errors: list[PlanIssue] = []
    for device in devices:
        applied = [p for p in policies if policy_matches(p, device)]
        sources: dict[GenericParamNames, list[str]] = {}
        for policy in applied:
            for concept_name in policy.settings:
                sources.setdefault(concept_name, []).append(policy.name)
        for concept_name, names in sources.items():
            if len(names) > 1:
                joined = ", ".join(sorted(names))
                errors.append(
                    PlanIssue(
                        device,
                        concept_name,
                        f"set by conflicting policies: {joined}",
                    )
                )
        for policy in applied:
            for concept_name, value in policy.settings.items():
                if len(sources.get(concept_name, [])) > 1:
                    continue
                res = resolve(device, CATALOG[concept_name], mapping, value)
                _record(
                    device,
                    concept_name,
                    policy,
                    res,
                    writes,
                    warnings,
                    errors,
                )
    return Plan(
        writes=tuple(writes),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def _record(
    device: Device,
    concept_name: GenericParamNames,
    policy: Policy,
    res: Resolution,
    writes: list[PlannedWrite],
    warnings: list[PlanIssue],
    errors: list[PlanIssue],
) -> None:
    if res.status is ResolutionStatus.RESOLVED:
        assert res.command_class is not None
        assert res.property is not None
        assert res.value is not None
        writes.append(
            PlannedWrite(
                device=device,
                concept=concept_name,
                policy=policy.name,
                command_class=res.command_class,
                property=res.property,
                property_key=res.property_key,
                value=res.value,
            )
        )
    elif res.status is ResolutionStatus.NOT_APPLICABLE:
        warnings.append(PlanIssue(device, concept_name, res.reason))
    else:
        errors.append(PlanIssue(device, concept_name, res.reason))
