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
    property_: int | str


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

    Both fields are casefolded at construction so the quirk lookup
    matches a device's reported identity case-insensitively, the same
    rule ``Selector`` uses -- a manufacturer/model string that differs
    only in case between the config DB and the device still finds its
    quirk.
    """

    manufacturer: str
    model: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "manufacturer", self.manufacturer.casefold())
        object.__setattr__(self, "model", self.model.casefold())


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
    # Provenance: a flat string-string mapping recording which
    # zwave-js snapshot the locators / quirks were classified
    # against (typically ``zwave_js_tag`` + ``zwave_js_commit`` +
    # ``zwave_js_commit_date``). Pure metadata for the handler to
    # log at startup; the resolver ignores it. Unknown subkeys are
    # accepted for forward-compat -- new provenance fields can be
    # added without touching the loader.
    metadata: Mapping[str, str] = field(default_factory=dict)

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

    @classmethod
    def from_dict(cls, raw: object) -> MappingTable:
        """Build from the generated, checked-in mapping JSON.

        The DB-scan generator emits this; nothing else hand-edits it.
        Validation is strict: any malformed entry raises ``ValueError``
        with the path of the offending field, so a generator bug fails
        loudly at load rather than silently mis-resolving. The disjoint
        label/token invariant is enforced by ``__post_init__``.

        Expected shape::

            {
              "locators": {
                "<concept>": {"labels": [...]}
                             OR {"command_class": int,
                                 "property": int | str}
              },
              "quirks": {
                "<concept>": {"<manufacturer>": {"<model>":
                  {"invert"?: bool,
                   "off_value"?: int | null,
                   "on_value"?: int | null}}}
              },
              "off_labels": [...], "on_labels": [...],
              "low_tokens": [...], "high_tokens": [...],
              "metadata": {"zwave_js_tag": "...",
                           "zwave_js_commit": "...", ...}
            }

        Every top-level key except ``locators`` is optional.
        """

        if not isinstance(raw, Mapping):
            raise ValueError("mapping: root must be a mapping")
        unknown = set(raw) - {
            "metadata",
            "locators",
            "quirks",
            "off_labels",
            "on_labels",
            "low_tokens",
            "high_tokens",
        }
        if unknown:
            raise ValueError(
                f"mapping: unknown top-level key(s): {sorted(unknown)}"
            )
        return cls(
            locators=_parse_locators(raw.get("locators")),
            quirks=_parse_quirks(raw.get("quirks")),
            off_labels=frozenset(
                _parse_str_list(raw.get("off_labels"), "off_labels")
            ),
            on_labels=frozenset(
                _parse_str_list(raw.get("on_labels"), "on_labels")
            ),
            low_tokens=_parse_str_list(raw.get("low_tokens"), "low_tokens"),
            high_tokens=_parse_str_list(raw.get("high_tokens"), "high_tokens"),
            metadata=_parse_metadata(raw.get("metadata")),
        )


_CONCEPT_NAMES: dict[str, GenericParamNames] = {
    n.value: n for n in GenericParamNames
}


def _concept(name: object, where: str) -> GenericParamNames:
    if not isinstance(name, str) or name not in _CONCEPT_NAMES:
        raise ValueError(f"{where}: unknown concept {name!r}")
    return _CONCEPT_NAMES[name]


def _parse_locators(raw: object) -> Mapping[GenericParamNames, Locator]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("mapping: 'locators' must be a mapping")
    out: dict[GenericParamNames, Locator] = {}
    for name, spec in raw.items():
        concept = _concept(name, "locators")
        out[concept] = _parse_locator(spec, concept)
    return out


def _parse_locator(spec: object, concept: GenericParamNames) -> Locator:
    where = f"locators[{concept.value!r}]"
    if not isinstance(spec, Mapping):
        raise ValueError(f"{where}: must be a mapping")
    has_labels = "labels" in spec
    has_cc = "command_class" in spec
    if has_labels == has_cc:
        raise ValueError(
            f"{where}: needs exactly one of 'labels' or 'command_class'"
        )
    allowed = {"labels"} if has_labels else {"command_class", "property"}
    extra = set(spec) - allowed
    if extra:
        raise ValueError(f"{where}: unknown key(s): {sorted(extra)}")
    if has_labels:
        labels = spec["labels"]
        if (
            not isinstance(labels, list)
            or not labels
            or not all(isinstance(x, str) and x for x in labels)
        ):
            raise ValueError(
                f"{where}: 'labels' must be a non-empty list of "
                f"non-empty strings"
            )
        return LabelMatch(tuple(labels))
    cc = spec.get("command_class")
    prop = spec.get("property")
    if isinstance(cc, bool) or not isinstance(cc, int):
        raise ValueError(f"{where}: 'command_class' must be an int")
    if isinstance(prop, bool) or not isinstance(prop, (int, str)):
        raise ValueError(f"{where}: 'property' must be an int or string")
    return FixedValueId(cc, prop)


def _parse_quirks(
    raw: object,
) -> Mapping[tuple[GenericParamNames, ModelId], ModelQuirk]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("mapping: 'quirks' must be a mapping")
    out: dict[tuple[GenericParamNames, ModelId], ModelQuirk] = {}
    for concept_name, by_mfg in raw.items():
        concept = _concept(concept_name, "quirks")
        if not isinstance(by_mfg, Mapping):
            raise ValueError(
                f"quirks[{concept_name!r}]: must be a mapping of "
                f"manufacturer -> model -> quirk"
            )
        for mfg, by_model in by_mfg.items():
            if not isinstance(mfg, str) or not mfg:
                raise ValueError(
                    f"quirks[{concept_name!r}]: manufacturer key must "
                    f"be a non-empty string"
                )
            if not isinstance(by_model, Mapping):
                raise ValueError(
                    f"quirks[{concept_name!r}][{mfg!r}]: must be a "
                    f"mapping of model -> quirk"
                )
            for model, q in by_model.items():
                if not isinstance(model, str) or not model:
                    raise ValueError(
                        f"quirks[{concept_name!r}][{mfg!r}]: model "
                        f"key must be a non-empty string"
                    )
                out[(concept, ModelId(mfg, model))] = _parse_quirk(
                    q, concept, mfg, model
                )
    return out


def _parse_quirk(
    raw: object, concept: GenericParamNames, mfg: str, model: str
) -> ModelQuirk:
    where = f"quirks[{concept.value!r}][{mfg!r}][{model!r}]"
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where}: must be a mapping")
    extra = set(raw) - {"invert", "off_value", "on_value"}
    if extra:
        raise ValueError(f"{where}: unknown key(s): {sorted(extra)}")
    invert = raw.get("invert", False)
    if not isinstance(invert, bool):
        raise ValueError(f"{where}: 'invert' must be a bool")
    return ModelQuirk(
        invert=invert,
        off_value=_parse_opt_int(raw.get("off_value"), f"{where}.off_value"),
        on_value=_parse_opt_int(raw.get("on_value"), f"{where}.on_value"),
    )


def _parse_opt_int(raw: object, where: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{where}: must be an int or null")
    return raw


def _parse_metadata(raw: object) -> Mapping[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("mapping: 'metadata' must be a mapping")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(
                f"mapping: metadata key must be a string, got "
                f"{type(key).__name__}"
            )
        if not isinstance(value, str):
            raise ValueError(
                f"mapping: metadata[{key!r}] must be a string, got "
                f"{type(value).__name__}"
            )
        out[key] = value
    return out


def _parse_str_list(raw: object, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(
        isinstance(x, str) and x for x in raw
    ):
        raise ValueError(
            f"mapping: {where!r} must be a list of non-empty strings"
        )
    seen: set[str] = set()
    for item in raw:
        if item in seen:
            raise ValueError(f"mapping: {where!r} contains duplicate {item!r}")
        seen.add(item)
    return tuple(raw)


# -- Device + parameter metadata (resolver inputs) ---------------


@dataclass(frozen=True)
class ParamId:
    """A device parameter's identity: command class, property, and key.

    The hashable key for a device's live values and for the convergence
    join (a planned write looked up against the current value).
    ``property_key`` is set for bitmask / partial parameters, ``None``
    otherwise. Distinct from ``FixedValueId`` (a mapping *locator*, which
    carries no ``property_key``).
    """

    command_class: int
    property_: int | str
    property_key: int | None = None


@dataclass(frozen=True)
class ParamMeta:
    """One device parameter as zwave-js reports it.

    ``id`` is the parameter's ``ParamId`` (command class / property / key).
    ``states`` maps a raw value to its option label (e.g.
    ``{0: "Disable", 1: "Enable"}``), empty for a bare numeric range;
    ``range`` is the inclusive raw ``(min, max)`` bounds, ``None`` when the
    parameter reports none.
    """

    id: ParamId
    label: str
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

    On ``RESOLVED``, ``id`` (a ParamId) and ``value`` are the concrete
    write target; otherwise both are ``None`` and ``reason`` explains the
    warning / error.
    """

    status: ResolutionStatus
    id: ParamId | None = None
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
            if p.id.command_class == locator.command_class
            and p.id.property_ == locator.property_
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
        id=param.id,
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
    id: ParamId
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
class UnusedSetting:
    """A configured policy / setting that applied to no device.

    Aggregate config hygiene, distinct from the per-device
    not-applicable warnings: a whole specified setting that landed on
    nothing. ``concept`` is ``None`` when the policy's selector matched
    no device at all (the entire policy is inert); otherwise it names the
    one setting that no matched device exposed. ``reason`` is the
    human-readable explanation for the report.
    """

    policy: str
    concept: GenericParamNames | None
    reason: str


@dataclass(frozen=True)
class Plan:
    """Result of ``evaluate_policies``.

    ``writes`` are the concrete writes; ``warnings`` are
    not-applicable concepts (a selected device lacks the parameter);
    ``errors`` are conflicts and unmappable values; ``unused`` are
    configured policies / settings that applied to no device at all.
    """

    writes: tuple[PlannedWrite, ...] = ()
    warnings: tuple[PlanIssue, ...] = ()
    errors: tuple[PlanIssue, ...] = ()
    unused: tuple[UnusedSetting, ...] = ()


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

    A configured policy / setting that lands on no device is an
    ``unused`` finding (aggregate config hygiene): a policy whose
    selector matched nothing, or a setting no matched device exposed
    (NOT_APPLICABLE on every match). A setting blocked everywhere by a
    conflict or a resolution error is NOT unused -- it already surfaces
    on the error report -- so unused stays the inert-config signal.
    """

    writes: list[PlannedWrite] = []
    warnings: list[PlanIssue] = []
    errors: list[PlanIssue] = []
    matched_policies: set[str] = set()
    resolved_keys: set[tuple[str, GenericParamNames]] = set()
    blocked_keys: set[tuple[str, GenericParamNames]] = set()
    for device in devices:
        applied = [p for p in policies if policy_matches(p, device)]
        matched_policies.update(p.name for p in applied)
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
                blocked_keys.update((name, concept_name) for name in names)
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
                key = (policy.name, concept_name)
                if res.status is ResolutionStatus.RESOLVED:
                    resolved_keys.add(key)
                elif res.status is not ResolutionStatus.NOT_APPLICABLE:
                    blocked_keys.add(key)
    return Plan(
        writes=tuple(writes),
        warnings=tuple(warnings),
        errors=tuple(errors),
        unused=_unused(policies, matched_policies, resolved_keys, blocked_keys),
    )


def _unused(
    policies: Sequence[Policy],
    matched_policies: set[str],
    resolved_keys: set[tuple[str, GenericParamNames]],
    blocked_keys: set[tuple[str, GenericParamNames]],
) -> tuple[UnusedSetting, ...]:
    """Configured policies / settings that landed on no device.

    A policy that matched nothing yields one policy-level finding (its
    settings aren't enumerated -- the whole policy is inert). A matched
    policy yields a per-setting finding for each concept that neither
    resolved nor was blocked anywhere, i.e. NOT_APPLICABLE on every
    matched device.
    """

    unused: list[UnusedSetting] = []
    for policy in policies:
        if policy.name not in matched_policies:
            unused.append(
                UnusedSetting(policy.name, None, "selector matched no devices")
            )
            continue
        for concept_name in policy.settings:
            key = (policy.name, concept_name)
            if key in resolved_keys or key in blocked_keys:
                continue
            unused.append(
                UnusedSetting(
                    policy.name,
                    concept_name,
                    "no matched device exposes this setting",
                )
            )
    return tuple(unused)


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
        assert res.id is not None
        assert res.value is not None
        writes.append(
            PlannedWrite(
                device=device,
                concept=concept_name,
                policy=policy.name,
                id=res.id,
                value=res.value,
            )
        )
    elif res.status is ResolutionStatus.NOT_APPLICABLE:
        warnings.append(PlanIssue(device, concept_name, res.reason))
    else:
        errors.append(PlanIssue(device, concept_name, res.reason))
